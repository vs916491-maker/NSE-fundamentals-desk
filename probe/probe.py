"""One-off probe: fetch each NSE source and save trimmed samples so field names can be checked."""
import json, sys, os, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
from nse import NSE

F, T = "20-10-2026", "24-10-2026"
out = {}
n = NSE()

def trim(x, k=3):
    if isinstance(x, list):
        return {"len": len(x), "sample": x[:k]}
    if isinstance(x, dict):
        return {kk: trim(v, k) for kk, v in list(x.items())[:40]}
    if isinstance(x, str) and len(x) > 1500:
        return x[:1500] + "...<cut>"
    return x

def probe(name, fn):
    try:
        out[name] = {"ok": True, "data": trim(fn())}
    except Exception as e:
        out[name] = {"ok": False, "err": repr(e), "tb": traceback.format_exc()[-800:]}
    print(name, out[name]["ok"])

probe("announcements", lambda: n.get("/api/corporate-announcements", {"index": "equities", "from_date": F, "to_date": T}))
probe("results", lambda: n.get("/api/corporates-financial-results", {"index": "equities", "period": "Quarterly", "from_date": F, "to_date": T}))
probe("shareholding", lambda: n.get("/api/corporate-share-holdings-master", {"index": "equities", "from_date": "01-10-2026", "to_date": T}))
probe("pit", lambda: n.get("/api/corporates-pit", {"index": "equities", "from_date": F, "to_date": T}))
probe("bulk_api", lambda: n.get("/api/historical/bulk-deals", {"from": F, "to": T}))
probe("block_api", lambda: n.get("/api/historical/block-deals", {"from": F, "to": T}))
probe("bulk_csv", lambda: n.get("https://nsearchives.nseindia.com/content/equities/bulk.csv", raw=True).decode()[:1500])
probe("block_csv", lambda: n.get("https://nsearchives.nseindia.com/content/equities/block.csv", raw=True).decode()[:1500])
probe("results_cmp_TCS", lambda: n.get("/api/results-comparision", {"symbol": "TCS"}))
probe("results_cmp_HDFCBANK", lambda: n.get("/api/results-comparision", {"symbol": "HDFCBANK"}))
probe("quote_LT", lambda: n.get("/api/quote-equity", {"symbol": "LT"}))
probe("equity_list", lambda: n.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", raw=True).decode()[:600])

# sample XBRL docs
try:
    r = out["results"]["data"]["sample"][0] if out["results"]["ok"] else None
    if r and r.get("xbrl"):
        out["results_xbrl"] = n.get(r["xbrl"], raw=True).decode(errors="ignore")[:12000]
except Exception as e:
    out["results_xbrl"] = repr(e)
try:
    s = out["shareholding"]["data"]["sample"][0] if out["shareholding"]["ok"] else None
    if s and s.get("xbrl"):
        out["sh_xbrl"] = n.get(s["xbrl"], raw=True).decode(errors="ignore")[:15000]
except Exception as e:
    out["sh_xbrl"] = repr(e)

os.makedirs("probe", exist_ok=True)
json.dump(out, open("probe/out.json", "w"), indent=1, default=str)
