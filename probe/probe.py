"""Probe round 4: integrated filing history by symbol."""
import json, sys, os, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
from nse import NSE
n = NSE(); out = {}
for p in [{"index": "equities", "symbol": "TCS", "type": "Integrated Filing- Financials"},
          {"index": "equities", "symbol": "TCS"},
          {"index": "equities", "symbol": "TCS", "type": "Integrated Filing- Financials", "from_date": "01-01-2025", "to_date": "24-10-2026", "size": 100},
          {"index": "equities", "symbol": "HDFCBANK", "type": "Integrated Filing- Financials", "size": 100}]:
    try:
        r = n.get("/api/integrated-filing-results", p)
        d = r.get("data") or []
        out[json.dumps(p)] = {"total": r.get("totalCount"), "rows": [(x["symbol"], x["qe_Date"], x.get("consolidated"), x.get("type_Sub"), x.get("creation_Date"), x["xbrl"][-60:]) for x in d[:40]],
                              "types": collections.Counter(x.get("type") for x in d).most_common()}
    except Exception as e:
        out[json.dumps(p)] = repr(e)[:200]
json.dump(out, open("probe/out.json", "w"), indent=1, default=str)
