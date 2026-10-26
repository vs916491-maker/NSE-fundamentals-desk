import json, sys, os, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
from nse import NSE
import xlrd
n = NSE(); out = {}
for d in ("23-Oct-2026", "22-Oct-2026"):
    try:
        raw = n.get(f"https://nsearchives.nseindia.com/content/fo/fii_stats_{d}.xls", raw=True)
        wb = xlrd.open_workbook(file_contents=raw)
        sh = wb.sheet_by_index(0)
        out[d] = [[str(c) for c in sh.row_values(i)] for i in range(min(sh.nrows, 30))]
    except Exception as e:
        out[d] = repr(e)
for opt, F, T in (("bulk_deals", "01-07-2026", "23-10-2026"), ("block_deals", "01-07-2026", "23-10-2026"), ("bulk_deals", "01-01-2026", "30-06-2026")):
    try:
        r = n.get("/api/historicalOR/bulk-block-short-deals", {"optionType": opt, "from": F, "to": T})
        d = r.get("data") or []
        out[f"{opt}_{F}"] = {"n": len(d), "keys": list(r.keys()), "first": d[0]["BD_DT_DATE"] if d else None, "last": d[-1]["BD_DT_DATE"] if d else None}
    except Exception as e:
        out[f"{opt}_{F}"] = repr(e)[:200]
for p in ({"date": "22-10-2026"}, {"from": "20-10-2026", "to": "23-10-2026"}):
    try:
        out["fiidii_" + json.dumps(p)] = json.dumps(n.get("/api/fiidiiTradeReact", p))[:400]
    except Exception as e:
        out["fiidii_" + json.dumps(p)] = repr(e)[:200]
json.dump(out, open("probe/out.json", "w"), indent=1)
