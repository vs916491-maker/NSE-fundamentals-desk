"""Per-stock fundamentals for the Stock page.

For every NSE stock the latest quarterly results filing is read, together with
the filings it is compared against: the previous quarter, the same quarter last
year (which also gives last year's year-to-date) and the last full year. NSE's
results XBRL carries only the quarter and the year to date, so these are
separate filings. A compact record per stock goes to site/data/fund/<letter>.json:
sales, operating profit, net profit, EPS, other income, finance cost,
depreciation, exceptional items and tax per period, the 12-month totals and the
share count. Closing prices go to a small separate file (fund/prices.json) every
evening, so P/E and Mcap/Sales stay current without rewriting the big files.

Today's results filers are refreshed first; then stocks with no record yet
(most traded first) and finally records not checked for RECHECK_DAYS, all
within a time budget, so the first full pass is spread over a few evenings.
"""
import logging
import os
import time
from datetime import date

import xbrl

log = logging.getLogger("fund")

QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")
RECHECK_DAYS = 10      # look again for a newer filing after this many days
EMPTY_RECHECK = 30     # stocks with no usable filing: look again after this many days
KEEP = ("rev", "op", "pat", "pbt", "eps", "oi", "fin", "dep", "exc", "tax")


def shard(sym: str) -> str:
    c = (sym or "_")[0].upper()
    return c if "A" <= c <= "Z" else "0"


def months(m):
    if not m or not m.get("start") or not m.get("end"):
        return None
    days = (date.fromisoformat(m["end"]) - date.fromisoformat(m["start"])).days
    return round(days / 30.44)


def _slim(m):
    if not m:
        return None
    out = {k: m.get(k) for k in KEEP if m.get(k) is not None}
    out["s"], out["e"] = m.get("start"), m.get("end")
    return out


def _prev_qe(qe: date) -> date:
    m, y = qe.month - 3, qe.year
    if m <= 0:
        m, y = m + 12, y - 1
    return date(y, m, {3: 31, 6: 30, 9: 30, 12: 31}[m])


def _year_ago(qe: date) -> date:
    return date(qe.year - 1, qe.month, qe.day)


def ttm(p):
    """Trailing 12 months, field by field, from the collected periods."""
    q, py, ytd, ytd_py, fy = (p.get(k) for k in ("q", "py", "ytd", "ytd_py", "fy"))
    out = {}
    for k in ("rev", "op", "pat", "eps"):
        v = None
        if ytd and (months(ytd) or 0) >= 12:
            v = ytd.get(k)
        elif ytd and ytd_py and fy and None not in (ytd.get(k), ytd_py.get(k), fy.get(k)):
            v = fy[k] + ytd[k] - ytd_py[k]              # last full year + this year so far - same part of last year
        elif not ytd and q and py and fy and None not in (q.get(k), py.get(k), fy.get(k)):
            v = fy[k] + q[k] - py[k]                    # first quarter of the year
        if v is not None:
            out[k] = round(v, 2)
    return out or None


def _odd(a, b):
    """A >20x sales jump between two filings is almost always a unit error in one of them."""
    ra, rb = (a or {}).get("rev"), (b or {}).get("rev")
    return bool(ra and rb and (ra / rb > 20 or ra / rb < 0.05))


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

    def _shares(self, sym):
        try:
            return self.c.shares(sym)
        except Exception as e:  # noqa: BLE001
            log.warning("shares %s: %s", sym, e)
            return None

    def refresh(self, sym, force=False):
        """Rebuild one stock's record if a newer quarter was filed. True when the record changed."""
        today = date.today().isoformat()
        hist = {}
        for h in sorted(self.c.fin_listing(sym), key=lambda x: x.get("creation_Date") or ""):
            qe = self.parse_date(h.get("qe_Date") or "")
            if qe and h.get("xbrl") and qe.isoformat()[5:] in QUARTER_ENDS:
                hist[(h.get("consolidated") or "Standalone", qe)] = h  # later filings (revisions) overwrite
        if not hist:
            self.state[sym] = {"qe": None, "checked": today}
            return False
        latest = max(q for _, q in hist)
        old = self.rows.get(sym)
        if old and old.get("qe") == latest.isoformat() and not force:
            self.state[sym] = {"qe": old["qe"], "checked": today}
            if not old.get("sh"):
                old["sh"] = self._shares(sym)
            return False
        cache_path = os.path.join(self.c.cache_dir, "fin", f"{sym}.json")
        cache = self.jload(cache_path, {})

        def parse(nature, qe):
            h = hist.get((nature, qe))
            if not h:
                return None
            m = self.c.fin_metrics(sym, nature, qe, h["xbrl"], cache)
            return m if m and m.get("_v") == xbrl.FIN_VERSION else None

        rec = None
        for nature in sorted({n for n, q in hist if q == latest}, key=lambda n: 0 if n.startswith("Cons") else 1):
            cur = parse(nature, latest)
            if not cur or cur.get("rev") is None:
                continue
            cp = cur.get("periods") or {}
            p = {"q": cp.get("q")}
            if cp.get("ytd") and (months(cp["ytd"]) or 0) > 3:
                p["ytd"] = cp["ytd"]
            pqf = parse(nature, _prev_qe(latest))
            pyf = parse(nature, _year_ago(latest))
            if pqf:
                p["pq"] = (pqf.get("periods") or {}).get("q")
            if pyf:
                pyp = pyf.get("periods") or {}
                p["py"] = pyp.get("q")
                if p.get("ytd"):
                    y = pyp.get("ytd") or (pyp.get("q") if months(p["ytd"]) == 3 else None)
                    if y and months(y) == months(p["ytd"]):
                        p["ytd_py"] = y
            # last full year (only needed before the fourth quarter)
            if not (p.get("ytd") and months(p["ytd"]) >= 12):
                fy_end = None
                try:
                    fy_end = date.fromisoformat(cur.get("fy_end") or "")
                    fy_end = date(fy_end.year - 1, fy_end.month, fy_end.day)
                    while fy_end >= latest:
                        fy_end = date(fy_end.year - 1, fy_end.month, fy_end.day)
                except ValueError:
                    fy_end = None
                if fy_end is None:
                    ends = [q for n, q in hist if n == nature and q < latest and q.month == 3]
                    fy_end = max(ends) if ends else None
                if fy_end:
                    fyf = pqf if fy_end == _prev_qe(latest) else parse(nature, fy_end)
                    fyy = ((fyf or {}).get("periods") or {}).get("ytd")
                    if fyy and months(fyy) >= 12:
                        p["fy"] = fyy
            for k in ("pq", "py", "ytd_py", "fy"):
                if _odd(p.get("q") if k in ("pq", "py") else p.get("ytd") or p.get("q"), p.get(k)):
                    p.pop(k, None)
            h = hist[(nature, latest)]
            rec = {"n": h.get("smName") or h.get("cmName") or (old or {}).get("n"), "qe": latest.isoformat(),
                   "nat": nature, "filed": h.get("creation_Date"), "x": h.get("ixbrl") or h.get("xbrl"),
                   "finco": bool(cur.get("financial"))}
            for k, v in p.items():
                if v:
                    rec[k] = _slim(v)
            t = ttm(p)
            if t:
                rec["ttm"] = t
            break
        self.jsave(cache_path, cache)
        if rec is None:
            self.state[sym] = {"qe": None, "checked": today}
            return False
        rec["sh"] = (old or {}).get("sh") if old and old.get("qe") == rec["qe"] else None
        rec["sh"] = rec["sh"] or self._shares(sym)
        if not rec["sh"]:
            rec.pop("sh")
        self.rows[sym] = rec
        self.state[sym] = {"qe": rec["qe"], "checked": today}
        return True

    def run(self, today_syms, minutes):
        """Today's filers first, then stocks never read (most traded first), then stale ones."""
        end = time.time() + minutes * 60
        today = date.today()
        order = sorted(self.c.close, key=lambda s: -(self.c.turnover.get(s) or 0))
        rank = {s: i for i, s in enumerate(order)}
        fresh = set(today_syms)

        def due(sym):
            if sym in fresh:
                return 0
            st = self.state.get(sym)
            if not st:
                return 1
            age = (today - date.fromisoformat(st["checked"])).days
            if st.get("qe") is None:
                return 3 if age >= EMPTY_RECHECK else None
            return 2 if age >= RECHECK_DAYS else None

        todo = sorted((d, rank.get(s, 10 ** 6), s) for s in set(order) | fresh if (d := due(s)) is not None)
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
        never = sum(1 for s in order if s not in self.state)
        print(f"::notice title=Fundamentals::{done} stocks checked, {new} updated, {len(self.rows)} with data; "
              f"{never} of {len(order)} traded stocks not read yet")
        return never

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        shards = {}
        for sym, r in self.rows.items():
            shards.setdefault(shard(sym), {})[sym] = r
        for k, rows in shards.items():
            self.jsave(os.path.join(self.dir, f"{k}.json"), dict(sorted(rows.items())))
        prices = dict(self.c.close)  # every traded stock (the watchlist uses them too)
        if prices:
            self.jsave(os.path.join(self.dir, "prices.json"), {"d": self.c.close_date, "p": dict(sorted(prices.items()))})
        self.jsave(self.state_path, self.state)
