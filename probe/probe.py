import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
from nse import NSE
n = NSE(); out = {}
n.s.headers["Referer"] = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"
try: n.s.get("https://www.nseindia.com/report-detail/display-bulk-and-block-deals", timeout=20)
except Exception: pass
base = {"optionType": "bulk_deals", "from": "23-10-2026", "to": "23-10-2026"}
for name, extra, raw in (("json_day", {}, False), ("csv_day", {"csv": "true"}, True),
                         ("csv_range", {"csv": "true", "from": "01-10-2026"}, True)):
    try:
        r = n.get("/api/historicalOR/bulk-block-short-deals", {**base, **extra}, raw=raw)
        if raw:
            t = r.decode("utf-8-sig", errors="ignore")
            out[name] = {"lines": t.count("\n"), "head": t[:600]}
        else:
            out[name] = {"n": len(r.get("data") or [])}
    except Exception as e:
        out[name] = repr(e)[:200]
json.dump(out, open("probe/out.json", "w"), indent=1)
