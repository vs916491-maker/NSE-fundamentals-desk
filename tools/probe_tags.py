"""Temporary: run collector/finco.py on real filings and print the result."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
import nse, finco
from datetime import datetime, date

n = nse.NSE()
pd = lambda s: datetime.strptime((s or "01-Jan-2000")[:11].title(), "%d-%b-%Y").date()
for sym in sys.argv[1].split(","):
    try:
        r = n.get("/api/integrated-filing-results", {"index": "equities", "symbol": sym, "type": "Integrated Filing- Financials", "size": 100}) or {}
        rows = [h for h in (r.get("data") or []) if h.get("xbrl")]
        for qe in (date(2026, 9, 30), date(2026, 6, 30), date(2025, 9, 30)):
            for h in rows:
                if pd(h.get("qe_Date")) == qe:
                    doc = n.get(h["xbrl"], raw=True).decode(errors="ignore")
                    print("RES", sym, h.get("consolidated"), qe, json.dumps(finco.parse(doc, qe)))
    except Exception as e:
        print(f"ERR {sym}: {e!r}")
