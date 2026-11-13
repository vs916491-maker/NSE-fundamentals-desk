"""Temporary probe (removed before merge): results-filing history depth, corporate actions, bhavcopy speed."""
import os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
import nse
from datetime import datetime, date, timedelta
n = nse.NSE()
pd = lambda s: datetime.strptime((s or "01-Jan-2000")[:11].title(), "%d-%b-%Y").date()
for sym in ["WABAG", "HDFCBANK", "TCS", "HFCL", "BAJFINANCE"]:
    r = n.get("/api/integrated-filing-results", {"index": "equities", "symbol": sym, "type": "Integrated Filing- Financials", "size": 100}) or {}
    rows = r.get("data") or []
    qs = sorted({(h.get("qe_Date"), h.get("consolidated"), (h.get("creation_Date") or "")[:11], bool(h.get("xbrl"))) for h in rows}, key=lambda x: pd(x[0]))
    print("LIST", sym, len(rows), json.dumps(qs[:6]), "...", json.dumps(qs[-3:]))
    print("KEYS", sorted(rows[0].keys()) if rows else None)
# older endpoint
for path, params in [("/api/corporates-financial-results", {"index": "equities", "symbol": "WABAG", "period": "Quarterly"})]:
    try:
        r = n.get(path, params, tries=2)
        rows = r if isinstance(r, list) else (r or {}).get("data") or []
        print("OLD", path, len(rows), json.dumps([{k: x.get(k) for k in ("toDate", "consolidated", "xbrl", "filingDate", "broadCastDate")} for x in rows[:4]])[:900])
    except Exception as e:
        print("OLD ERR", path, e)
# corporate actions, all stocks, window
for params in [{"index": "equities", "from_date": "01-04-2025", "to_date": "13-11-2026"}]:
    try:
        r = n.get("/api/corporates-corporateActions", params, tries=2)
        rows = r if isinstance(r, list) else (r or {}).get("data") or []
        sb = [x for x in rows if any(k in (x.get("subject") or "").lower() for k in ("split", "bonus", "sub-division", "consolidation"))]
        print("CA", len(rows), "split/bonus", len(sb), "KEYS", sorted(rows[0].keys()) if rows else None)
        for x in sb[:25]:
            print("CA1", json.dumps({k: x.get(k) for k in ("symbol", "subject", "exDate", "recDate", "series", "faceVal")}))
    except Exception as e:
        print("CA ERR", e)
# bhavcopy speed
t0 = time.time(); ok = 0; size = 0
d = date(2026, 11, 12)
for i in range(12):
    dd = d - timedelta(days=i)
    try:
        b = n.get(f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{dd.strftime('%d%m%Y')}.csv", raw=True, tries=1)
        ok += 1; size += len(b)
    except Exception as e:
        pass
print("BHAV", ok, "files", round(size / max(ok, 1) / 1024), "KB each", round(time.time() - t0, 1), "s total")
t0 = time.time()
try:
    b = n.get("https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_01042025.csv", raw=True, tries=1); print("BHAV old ok", len(b))
except Exception as e:
    print("BHAV old ERR", e)
