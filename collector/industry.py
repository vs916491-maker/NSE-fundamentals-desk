"""Stock -> industry, for the Ideas tab's themes.

NSE's basic industry (the finest of its four classification levels, e.g. "Railway Wagons",
"Aerospace & Defense") comes from the quote page's data API. Each stock is looked up once and kept in cache/industry.json; lookups that fail are
retried after RETRY_DAYS. Stocks NSE never classified fall back to the older industry name NSE puts on
corporate announcements (collected separately by ideas.py).

themes.csv groups those industry names into ~25 investment themes. Edit it to move an industry to a
different theme or to point a theme at another Sector Strength index (column ss_index).
"""
import csv
import logging
import os
import time
from datetime import date

log = logging.getLogger("industry")
HERE = os.path.dirname(os.path.abspath(__file__))
RETRY_DAYS = 30


def load_themes(path=os.path.join(HERE, "themes.csv")):
    """[(theme, ss_index, set_of_names)] in file order, and {lower-case name: theme}."""
    rows, lookup = [], {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            names = {m.strip() for m in (r.get("matches") or "").split("|") if m.strip()}
            rows.append((r["theme"].strip(), (r.get("ss_index") or "").strip(), names))
            for m in names:
                lookup.setdefault(m.lower(), r["theme"].strip())
    return rows, lookup


def theme_of(info, ann_ind, lookup):
    """Most specific name first: basic industry, industry, sector, then the announcement industry."""
    for k in ("basic", "industry", "sector"):
        v = (info or {}).get(k)
        if v and v.lower() in lookup:
            return lookup[v.lower()]
    if ann_ind and ann_ind.lower() in lookup:
        return lookup[ann_ind.lower()]
    # unmapped: show NSE's industry name itself so it can be added to themes.csv later
    return (info or {}).get("industry") or ann_ind or None


def _find(obj, key):
    if isinstance(obj, dict):
        if obj.get(key):
            return obj[key]
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            r = _find(v, key)
            if r:
                return r
    return None


def lookup_basic(n, sym):
    """NSE's basic industry for one stock, from the quote page's data API (the older /api/quote-equity
    now answers 403). Only the basic-industry level is in this response."""
    ref = f"https://www.nseindia.com/get-quote/equity/{sym}"
    n.s.headers["Referer"] = ref
    try:
        r = n.get("/api/NextApi/apiClient/GetQuoteApi",
                  {"functionName": "getSymbolData", "marketType": "N", "series": "EQ", "symbol": sym}, tries=2)
    except RuntimeError:
        n.s.get(ref, timeout=20)          # fresh cookies from the quote page, then one more try
        r = n.get("/api/NextApi/apiClient/GetQuoteApi",
                  {"functionName": "getSymbolData", "marketType": "N", "series": "EQ", "symbol": sym}, tries=1)
    b = _find(r, "basicIndustry")
    return b.strip() if isinstance(b, str) and b.strip() not in ("", "-", "NA") else None


def update(n, syms, path, jload, jsave, minutes=6.0):
    """Look up stocks that have no classification yet (in the order given). Returns the map."""
    m = jload(path, {})
    today = date.today()
    todo = []
    for s in syms:
        r = m.get(s)
        if r and (r.get("industry") or r.get("basic")):
            continue
        if r and r.get("checked") and not r.get("err") and (today - date.fromisoformat(r["checked"])).days < RETRY_DAYS:
            continue
        todo.append(s)
    if not todo:
        return m
    end = time.time() + minutes * 60
    done = found = fails = 0
    for s in todo:
        if time.time() > end:
            break
        try:
            basic = lookup_basic(n, s)
            m[s] = {"basic": basic, "checked": today.isoformat()} if basic else {"checked": today.isoformat()}
            found += bool(basic)
            fails = 0
        except Exception as e:  # noqa: BLE001
            m[s] = {"checked": today.isoformat(), "err": str(e)[:80]}
            fails += 1
            if fails >= 8:
                log.warning("industry lookups keep failing (%s); stopping for this run", e)
                break
        done += 1
        if done % 100 == 0:
            jsave(path, m)
    jsave(path, m)
    left = len(todo) - done
    log.info("industry: %d looked up, %d classified, %d left for later runs", done, found, left)
    print(f"::notice title=Industry map::{done} stocks looked up, {found} classified, {left} left for later runs")
    return m
