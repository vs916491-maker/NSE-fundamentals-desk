"""Per-stock fundamentals for the Stock page.

For every NSE stock the latest quarterly results filing is read once (its XBRL
already carries the previous quarter, same quarter last year, year-to-date and
last full year), and a compact record is kept in site/data/fund/<letter>.json:
sales, operating profit, net profit, EPS, other income, finance cost,
depreciation, exceptional items and tax for each of those periods, the
trailing-12-month totals and the share count. Prices go to a small separate
file (fund/prices.json) every evening, so P/E and Mcap/Sales stay current
without rewriting the big files.

New results filed today replace a stock's record the same evening. Stocks that
have no record yet are filled in the background (most-traded first), within a
time budget, so the first full pass is spread over a few evenings.
"""
import logging
import os
import time
from datetime import date, datetime, timedelta

import xbrl

log = logging.getLogger("fund")

QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")
RECHECK_DAYS = 10      # look again for a newer filing after this many days
EMPTY_RECHECK = 30     # stocks with no usable filing: look again after this many days
KEEP = ("rev", "op", "pat", "pbt", "eps", "oi", "fin", "dep", "exc", "tax")


def shard(sym: str) -> str:
    c = (sym or "_")[0].upper()
    return c if "A" <= c <= "Z" else "0"


def _slim(m):
    if not m:
        return None
    out = {k: m.get(k) for k in KEEP if m.get(k) is not None}
    out["s"], out["e"] = m.get("start"), m.get("end")
    return out


def _months(m):
    if not m or not m.get("start") or not m.get("end"):
        return None
    days = (date.fromisoformat(m["end"]) - date.fromisoformat(m["start"])).days
    return round(days / 30.44)


def ttm(periods):
    """Trailing 12 months from the periods of one filing, field by field."""
    q, py, ytd, ytd_py, fy = (periods.get(k) for k in ("q", "py", "ytd", "ytd_py", "fy"))
    out = {}
    for k in ("rev", "op", "pat", "eps"):
        v = None
        if ytd and (_months(ytd) or 0) >= 12:
            v = ytd.get(k)
        elif ytd and ytd_py and fy and None not in (ytd.get(k), ytd_py.get(k), fy.get(k)):
            v = fy[k] + ytd[k] - ytd_py[k]
        elif not ytd and q and py and fy and None not in (q.get(k), py.get(k), fy.get(k)):
            # first quarter of the year: last full year + this quarter - same quarter last year
            v = fy[k] + q[k] - py[k]
        if v is not None:
            out[k] = round(v, 2)
    return out or None


def record(name, nature, qe, filed, url, parsed, shares=None):
    p = parsed.get("periods") or {}
    rec = {"n": name, "qe": qe, "nat": nature, "filed": filed, "x": url,
           "finco": bool(parsed.get("financial"))}
    for k in ("q", "pq", "py", "ytd", "ytd_py", "fy"):
        s = _slim(p.get(k))
        if s:
            rec[k] = s
    t = ttm(p)
    if t:
        rec["ttm"] = t
    if shares:
        rec["sh"] = shares
    return rec


class Fund:
    def __init__(self, collector, data_dir, cache_dir, jload, jsave, parse_date):
        self.c, self.jload, self.jsave, self.parse_date = collector, jload, jsave, parse_date
        self.dir = os.path.join(data_dir, "fund")
        self.state_path = os.path.join(cache_dir, "fund_state.json")
        self.state = jload(self.state_path, {})
        self.rows = {}
        if os.path.isdir(self.dir):
            for f in os.listdir(self.dir):
                if f.endswith(".json") and f != "prices.json":
                    self.rows.update(jload(os.path.join(self.dir, f), {}))
        self.changed = 0

    # ----- today's filings (already parsed by the results step) -----
    def from_results(self, rows):
        for r in rows:
            sym, nature, qe = r["sym"], r.get("nature") or "Standalone", r["qe"]
            if qe[5:] not in QUARTER_ENDS:
                continue
            old = self.rows.get(sym)
            if old and old.get("qe", "") > qe:
                continue
            cache = self.jload(os.path.join(self.c.cache_dir, "fin", f"{sym}.json"), {})
            parsed = cache.get(f"{nature}|{qe}")
            if not parsed or parsed.get("_v") != xbrl.FIN_VERSION:
                continue
            sh = (old or {}).get("sh") or self._shares(sym)
            self.rows[sym] = record(r.get("name"), nature, qe, r.get("filed"), r.get("xbrl"), parsed, sh)
            self.state[sym] = {"qe": qe, "checked": date.today().isoformat()}
            self.changed += 1

    def _shares(self, sym):
        try:
            return self.c.shares(sym) if self.c.budget.ok() else None
        except Exception as e:  # noqa: BLE001
            log.warning("shares %s: %s", sym, e)
            return None

    # ----- one stock from its filing list -----
    def refresh(self, sym):
        listing = self.c.fin_listing(sym)
        best = {}
        for h in listing:
            qe = self.parse_date(h.get("qe_Date") or "")
            if not qe or not h.get("xbrl") or qe.isoformat()[5:] not in QUARTER_ENDS:
                continue
            nature = h.get("consolidated") or "Standalone"
            key = (qe, 0 if nature.startswith("Cons") else 1)
            if key not in best or (h.get("creation_Date") or "") > (best[key].get("creation_Date") or ""):
                best[key] = h
        today = date.today().isoformat()
        if not best:
            self.state[sym] = {"qe": None, "checked": today}
            return False
        latest_qe = max(k[0] for k in best)
        old = self.rows.get(sym)
        if old and old.get("qe") == latest_qe.isoformat() and old.get("x"):
            self.state[sym] = {"qe": old["qe"], "checked": today}
            if not old.get("sh"):
                sh = self._shares(sym)
                if sh:
                    old["sh"] = sh
                    self.changed += 1
            return False
        cache_path = os.path.join(self.c.cache_dir, "fin", f"{sym}.json")
        cache = self.jload(cache_path, {})
        for pref in (0, 1):  # consolidated first, standalone if that cannot be read
            h = best.get((latest_qe, pref))
            if not h:
                continue
            nature = h.get("consolidated") or "Standalone"
            parsed = self.c.fin_metrics(sym, nature, latest_qe, h["xbrl"], cache)
            if parsed and parsed.get("_v") == xbrl.FIN_VERSION and parsed.get("rev") is not None:
                self.jsave(cache_path, cache)
                sh = (old or {}).get("sh") or self._shares(sym)
                self.rows[sym] = record(h.get("smName") or h.get("cmName") or (old or {}).get("n"), nature,
                                        latest_qe.isoformat(), h.get("creation_Date"),
                                        h.get("ixbrl") or h.get("xbrl"), parsed, sh)
                self.state[sym] = {"qe": latest_qe.isoformat(), "checked": today}
                self.changed += 1
                return True
        self.jsave(cache_path, cache)
        self.state[sym] = {"qe": None, "checked": today}
        return False

    def backfill(self, minutes):
        """Fill stocks with no record first (most traded first), then re-check old ones."""
        end = time.time() + minutes * 60
        today = date.today()
        order = sorted(self.c.close, key=lambda s: -(self.c.turnover.get(s) or 0))

        def due(sym):
            st = self.state.get(sym)
            if not st:
                return 0
            age = (today - date.fromisoformat(st["checked"])).days
            if st.get("qe") is None:
                return 2 if age >= EMPTY_RECHECK else None
            return 1 if age >= RECHECK_DAYS else None

        todo = [(due(s), i, s) for i, s in enumerate(order)]
        todo = sorted(t for t in todo if t[0] is not None)
        done = new = 0
        for _, _, sym in todo:
            if time.time() > end:
                break
            try:
                new += bool(self.refresh(sym))
            except Exception as e:  # noqa: BLE001
                log.warning("fund %s: %s", sym, e)
            done += 1
            if done % 100 == 0:
                log.info("fundamentals: %d checked, %d updated, %d left", done, new, len(todo) - done)
                self.save()
        missing = sum(1 for s in order if s not in self.state)
        log.info("fundamentals backfill: %d checked, %d updated; %d stocks never checked yet", done, new, missing)
        return missing

    # ----- save -----
    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        shards = {}
        for sym, r in self.rows.items():
            shards.setdefault(shard(sym), {})[sym] = r
        for k, rows in shards.items():
            self.jsave(os.path.join(self.dir, f"{k}.json"), dict(sorted(rows.items())))
        prices = {s: self.c.close[s] for s in self.rows if s in self.c.close}
        self.jsave(os.path.join(self.dir, "prices.json"), {"d": self.c.close_date, "p": dict(sorted(prices.items()))})
        self.jsave(self.state_path, self.state)
