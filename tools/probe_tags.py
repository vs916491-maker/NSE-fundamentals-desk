"""Temporary: print every XBRL element in the latest results filing of a few banks / lenders."""
import os, sys, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
import nse, xbrl
from datetime import datetime

n = nse.NSE()
for sym in sys.argv[1].split(","):
    try:
        r = n.get("/api/integrated-filing-results", {"index": "equities", "symbol": sym, "type": "Integrated Filing- Financials", "size": 20}) or {}
        rows = [h for h in (r.get("data") or []) if h.get("xbrl")]
        rows.sort(key=lambda h: datetime.strptime((h.get("qe_Date") or "01-Jan-2000")[:11].title(), "%d-%b-%Y"), reverse=True)
        top = rows[0]["qe_Date"]
        for h in [x for x in rows if x["qe_Date"] == top][:2]:
            doc = n.get(h["xbrl"], raw=True).decode(errors="ignore")
            ctxs = xbrl._contexts(doc)
            print(f"\n===== {sym} | {h.get('consolidated')} | {h['qe_Date']} | {h['xbrl']} | {len(doc)} bytes")
            for cid, c in ctxs.items():
                print(f"CTX {cid} start={c['start']} end={c['end']} instant={c['instant']} dims={c['dims']}")
            seen = {}
            for ns, name, attrs, ctx, val in xbrl._FACT.findall(doc):
                v = val.strip()
                if not v or len(v) > 40:
                    continue
                seen.setdefault(name, []).append(f"{ctx}={v}")
            for name, vals in seen.items():
                print(f"F {name}: " + " ; ".join(vals[:6]))
    except Exception as e:
        print(f"ERR {sym}: {e!r}")
