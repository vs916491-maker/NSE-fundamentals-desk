"""Daily price history, split/bonus factors and EPS history for the Stock Screener's Price & P/E chart.

The chart covers the last 6 quarters up to today:
  price  = daily close from NSE's bhavcopy (one file per trading day, downloaded once)
  P/E    = that day's price / sum of the EPS of the last 4 quarters whose results had been filed by that day,
           so the line steps on each results day
  both are put in today's share units using NSE's split / bonus list (factor applies before the ex-date;
  a filing made before an ex-date reports EPS in the old units)

Files (all written by update()):
  site/data/px/index.json                 {"from": first day, "to": last day, "q": [quarter ends]}
  site/data/px/<quarter end>/<letter>.json {"d": [dates], "p": {SYM: [close or null per date]}}
      finished quarters never change again; only the current quarter's files are rewritten
  site/data/corp_actions.json             {"a": {SYM: [[ex-date, factor], ...]}}  factor = new shares per old share
  fund record key "eh"                    [[quarter end, quarter EPS, results filed on], ...] (last EH_QUARTERS quarters)

EPS comes from each quarter's own results filing (3-month column), never worked out from year totals, so
every number belongs to a known filing date. Quarters before March 2025 come from NSE's older results list
(/api/corporates-financial-results); later ones from the integrated-filing list the desk already uses.
"""
import logging
import os
import re
import shutil
import time
from datetime import date, datetime, timedelta

log = logging.getLogger("history")
EH_VERSION = 1
EH_QUARTERS = 11        # 6 chart quarters + enough before them for a 4-quarter EPS on the chart's first day
CHART_QUARTERS = 6
OLD_LIST = "/api/corporates-financial-results"
INTEGRATED_FROM = date(2025, 3, 31)   # first quarter in the integrated-filing list
BHAV = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{}.csv"
SERIES = ("EQ", "BE", "BZ", "SM", "ST")


# ---------- dates ----------
def prev_qe(qe: date) -> date:
    m = {3: (12, -1), 6: (3, 0), 9: (6, 0), 12: (9, 0)}[qe.month]
    y = qe.year + m[1]
    return date(y, m[0], 31 if m[0] in (3, 12) else 30)


def qe_of(d: date) -> date:
    """Quarter end of the quarter that contains d."""
    m = ((d.month - 1) // 3 + 1) * 3
    return date(d.year, m, 31 if m in (3, 12) else 30)


def quarters_back(qe: date, n: int):
    out = [qe]
    while len(out) < n:
        out.append(prev_qe(out[-1]))
    return out[::-1]


def window_start(latest_qe: date) -> date:
    """First day of the chart: start of the oldest of the last CHART_QUARTERS reported quarters."""
    first = quarters_back(latest_qe, CHART_QUARTERS)[0]
    return prev_qe(first) + timedelta(days=1)


def _nse_day(s):
    s = (s or "").strip()
    for fmt, n in (("%d-%b-%Y", 11), ("%d-%m-%Y", 10), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:n].title() if fmt == "%d-%b-%Y" else s[:n], fmt).date()
        except ValueError:
            pass
    return None


# ---------- split / bonus factors ----------
_BONUS = re.compile(r"bonus\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", re.I)
_FV = re.compile(r"from\s*r[es]\.?\s*([\d.]+)\s*/?-?\s*(?:per\s*(?:equity\s*)?share)?\s*to\s*r[es]\.?\s*([\d.]+)", re.I)


def ca_factor(subject: str):
    """New shares per old share for a bonus, split (sub-division) or consolidation; None for anything else."""
    s = subject or ""
    f = 1.0
    b = _BONUS.search(s)
    if b and float(b.group(2)) > 0:
        f *= (float(b.group(1)) + float(b.group(2))) / float(b.group(2))
    if re.search(r"split|sub-?division|consolidation", s, re.I):
        m = _FV.search(s)
        if m and float(m.group(2)) > 0:
            f *= float(m.group(1)) / float(m.group(2))
    return round(f, 6) if f != 1.0 and 0.01 < f < 100 else None


def update_corp_actions(n, frm: date, to: date):
    rows = n.get("/api/corporates-corporateActions",
                 {"index": "equities", "from_date": frm.strftime("%d-%m-%Y"), "to_date": to.strftime("%d-%m-%Y")}) or []
    rows = rows if isinstance(rows, list) else rows.get("data") or []
    out, seen = {}, set()
    for x in rows:
        f = ca_factor(x.get("subject"))
        ex = _nse_day(x.get("exDate"))
        sym = (x.get("symbol") or "").strip()
        if not f or not ex or not sym or (sym, ex, f) in seen:
            continue
        seen.add((sym, ex, f))
        out.setdefault(sym, []).append([ex.isoformat(), f])
    for v in out.values():
        v.sort()
    return out


# ---------- daily prices ----------
def parse_bhav(raw: str):
    """(trade date written inside the file, {symbol: close}). On an exchange holiday NSE serves a copy of the
    previous day's file, so the trade date is what tells a real trading day from a holiday."""
    lines = raw.splitlines()
    if not lines:
        return None, {}
    hdr = [h.strip() for h in lines[0].split(",")]
    try:
        si, se, ci = hdr.index("SYMBOL"), hdr.index("SERIES"), hdr.index("CLOSE_PRICE")
    except ValueError:
        return None, {}
    di = hdr.index("DATE1") if "DATE1" in hdr else None
    out, day = {}, None
    for ln in lines[1:]:
        r = ln.split(",")
        if len(r) > ci and r[se].strip() in SERIES:
            if day is None and di is not None:
                day = _nse_day(r[di])
            try:
                out[r[si].strip()] = round(float(r[ci]), 2)
            except ValueError:
                pass
    return day, out


def _shard(sym):
    c = (sym or "_")[0].upper()
    return c if "A" <= c <= "Z" else "0"


def _load_quarter(path, jload):
    """{date: {sym: close}} from one quarter's letter files."""
    out = {}
    if not os.path.isdir(path):
        return out
    for f in os.listdir(path):
        if not f.endswith(".json"):
            continue
        j = jload(os.path.join(path, f), {}) or {}
        ds = j.get("d") or []
        for d in ds:
            out.setdefault(d, {})
        for sym, arr in (j.get("p") or {}).items():
            for d, v in zip(ds, arr):
                if v is not None:
                    out[d][sym] = v
    return out


def _save_quarter(path, data, syms, jsave):
    dates = sorted(data)
    shards = {}
    for sym in syms:
        arr = [data[d].get(sym) for d in dates]
        if any(v is not None for v in arr):
            shards.setdefault(_shard(sym), {})[sym] = arr
    if os.path.isdir(path):
        shutil.rmtree(path)
    for k, p in shards.items():
        jsave(os.path.join(path, f"{k}.json"), {"d": dates, "p": dict(sorted(p.items()))})


def update_prices(c, syms, px_dir, state, jload, jsave, start: date, minutes):
    """Fill daily closes from `start` to the latest bhavcopy, newest days first. Returns days added."""
    end_t = time.time() + minutes * 60
    last = date.fromisoformat(c.close_date) if c.close_date else date.today()
    os.makedirs(px_dir, exist_ok=True)
    # drop quarters that fell out of the window
    for q in os.listdir(px_dir):
        if re.match(r"\d{4}-\d{2}-\d{2}$", q) and date.fromisoformat(q) < qe_of(start):
            shutil.rmtree(os.path.join(px_dir, q))
    quarters, dirty = {}, set()

    def q_data(d):
        qid = qe_of(d).isoformat()
        if qid not in quarters:
            quarters[qid] = _load_quarter(os.path.join(px_dir, qid), jload)
        return qid, quarters[qid]

    missing = set(state.get("missing") or [])
    added = errors = 0
    d = last
    while d >= start and time.time() < end_t:
        if d.weekday() < 5 and d.isoformat() not in missing:
            qid, data = q_data(d)
            if d.isoformat() not in data:
                try:
                    raw = c.n.get(BHAV.format(d.strftime("%d%m%Y")), raw=True, tries=2).decode(errors="ignore")
                    day, p = parse_bhav(raw)
                    if p and (day is None or day == d):
                        data[d.isoformat()] = {s: v for s, v in p.items() if s in syms}
                        dirty.add(qid)
                        added += 1
                    elif day is not None and day != d:
                        missing.add(d.isoformat())      # holiday: the file is a copy of an earlier day
                except Exception as e:  # noqa: BLE001
                    if "HTTP 404" in str(e) and (last - d).days > 3:
                        missing.add(d.isoformat())      # exchange holiday: no file
                    else:
                        errors += 1
                        if errors >= 8:
                            log.warning("daily prices: downloads keep failing (%s); stopping for this run", e)
                            break
        d -= timedelta(days=1)
    for qid in dirty:
        _save_quarter(os.path.join(px_dir, qid), quarters[qid], syms, jsave)
    state["missing"] = sorted(x for x in missing if x >= start.isoformat())
    # what is on disk now
    qids = sorted(q for q in os.listdir(px_dir) if re.match(r"\d{4}-\d{2}-\d{2}$", q))
    have, todo = 0, 0
    for q in qids:
        data = quarters.get(q) or _load_quarter(os.path.join(px_dir, q), jload)
        have += len(data)
    dd = start
    while dd <= last:
        if dd.weekday() < 5 and dd.isoformat() not in missing:
            todo += 1
        dd += timedelta(days=1)
    jsave(os.path.join(px_dir, "index.json"), {"from": start.isoformat(), "to": last.isoformat(), "q": qids,
                                               "days": have, "expected": todo})
    return added, max(0, todo - have)


# ---------- EPS history ----------
def _listings(c, sym, need_old):
    """{(nature, quarter end): [xbrl url, filed date]} from the integrated list (+ the older list if needed)."""
    out = {}

    def put(nat, qe, url, filed):
        # NSE sometimes lists a filing with no file ("-" or a link ending in "/-")
        if not qe or not url or not url.lower().startswith("http") or url.rstrip().endswith("/-"):
            return
        k = (nat, qe)
        if k in out:
            # a revision: keep the newest numbers, but the date the results first became public
            out[k] = [url, min(x for x in (out[k][1], filed) if x) if (out[k][1] or filed) else None]
        else:
            out[k] = [url, filed]

    for h in sorted(c.fin_listing(sym, strict=True), key=lambda x: x.get("creation_Date") or ""):
        filed = [x for x in (_nse_day(h.get("broadcast_Date")), _nse_day(h.get("creation_Date"))) if x]
        put(h.get("consolidated") or "Standalone", _nse_day(h.get("qe_Date")), h.get("xbrl"), min(filed) if filed else None)
    if need_old:
        r = c.n.get(OLD_LIST, {"index": "equities", "symbol": sym, "period": "Quarterly"}) or []
        rows = r if isinstance(r, list) else r.get("data") or []
        for h in sorted(rows, key=lambda x: x.get("broadCastDate") or x.get("filingDate") or ""):
            nat = "Standalone" if "non" in (h.get("consolidated") or "").lower() else "Consolidated"
            qe = _nse_day(h.get("toDate"))
            if qe and qe >= INTEGRATED_FROM:
                continue
            filed = [x for x in (_nse_day(h.get("broadCastDate")), _nse_day(h.get("filingDate"))) if x]
            put(nat, qe, h.get("xbrl"), min(filed) if filed else None)
    return out


def eps_history(c, sym, rec, jload, jsave):
    """[[quarter end, EPS, filed], ...] for the EH_QUARTERS quarters up to the record's latest quarter."""
    import xbrl
    latest = date.fromisoformat(rec["qe"])
    target = quarters_back(latest, EH_QUARTERS)
    nature = rec.get("nat") or "Standalone"
    lst = _listings(c, sym, need_old=target[0] < INTEGRATED_FROM)
    cache_path = os.path.join(c.cache_dir, "fin", f"{sym}.json")
    cache = jload(cache_path, {})
    out = []
    try:
        for qe in target:
            ent = lst.get((nature, qe))
            if not ent:
                out.append([qe.isoformat(), None, None])
                continue
            url, filed = ent
            try:
                m = c.fin_metrics(sym, nature, qe, url, cache, accept_old=True, strict=True)
            except Exception as e:  # noqa: BLE001
                if "HTTP 404" not in str(e):
                    raise               # network trouble: retry the whole stock next run
                m = None                # the listed file is gone: leave this quarter blank
                log.info("eps history %s %s: file missing on NSE", sym, qe)
            eps = None
            if m:
                q = (m.get("periods") or {}).get("q") if m.get("_v") == xbrl.FIN_VERSION else None
                eps = (q or {}).get("eps") if q else m.get("eps")
            out.append([qe.isoformat(), eps, filed.isoformat() if filed else None])
    finally:
        jsave(cache_path, cache)
    return out


def update_eps(fund, minutes):
    """Add / refresh "eh" on records (most traded first) within the time budget. Returns how many are left."""
    end_t = time.time() + minutes * 60
    c = fund.c
    todo = [s for s, r in fund.rows.items() if r.get("qe") and not (
        r.get("eh_v") == EH_VERSION and r.get("eh_q") == r["qe"] and r.get("eh"))]
    today = date.today().isoformat()
    todo = [s for s in todo if fund.rows[s].get("eh_try") != today]   # failed earlier today: next run
    todo.sort(key=lambda s: -(c.turnover.get(s) or 0))
    done = errors = in_a_row = 0
    for sym in todo:
        if time.time() > end_t:
            break
        rec = fund.rows[sym]
        try:
            rec["eh"] = eps_history(c, sym, rec, fund.jload, fund.jsave)
            rec["eh_q"], rec["eh_v"] = rec["qe"], EH_VERSION
            rec.pop("eh_try", None)
            done += 1
            in_a_row = 0
        except Exception as e:  # noqa: BLE001
            log.warning("eps history %s: %s", sym, e)
            rec["eh_try"] = today
            errors += 1
            in_a_row += 1
            if in_a_row >= 10:      # NSE is refusing us: stop for this run
                break
        if done and done % 100 == 0:
            fund.save()
    return done, len(todo) - done, errors


# ---------- one call from the collector ----------
def update(fund, data_dir, minutes=15.0):
    """Corporate actions (one call), daily prices, then EPS history with the time that is left."""
    c = fund.c
    t0 = time.time()
    today = date.today()
    latest = max((q for r in fund.rows.values() if r.get("qe") and (q := date.fromisoformat(r["qe"])) <= today), default=None)
    if not latest:
        return
    start = window_start(latest)
    state_path = os.path.join(c.cache_dir, "history_state.json")
    state = fund.jload(state_path, {})
    # split / bonus list: refreshed at most twice a day
    ca_path = os.path.join(data_dir, "corp_actions.json")
    if (state.get("ca_at") or "") < (datetime.now() - timedelta(hours=10)).isoformat():
        try:
            ca = update_corp_actions(c.n, start - timedelta(days=400), date.today() + timedelta(days=30))
            fund.jsave(ca_path, {"updated": date.today().isoformat(), "a": ca})
            state["ca_at"] = datetime.now().isoformat(timespec="minutes")
        except Exception as e:  # noqa: BLE001
            log.warning("corporate actions: %s", e)
    syms = set(fund.rows)
    added, days_left = update_prices(c, syms, os.path.join(data_dir, "px"), state, fund.jload, fund.jsave, start,
                                     max(1.0, minutes * 0.5))
    fund.jsave(state_path, state)
    left_min = max(1.0, minutes - (time.time() - t0) / 60)
    done, eps_left, errors = update_eps(fund, left_min)
    print(f"::notice title=Price and P/E history::daily prices: {added} days added, {days_left} left; "
          f"EPS history: {done} stocks done, {eps_left} left" + (f", {errors} errors (retried next run)" if errors else ""))
