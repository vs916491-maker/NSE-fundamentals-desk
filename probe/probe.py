import json, sys, os, io, csv, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
from nse import NSE
n = NSE(); out = {}
def tryget(name, path, params=None, raw=False, cut=3000):
    try:
        r = n.get(path, params, raw=raw)
        if raw:
            r = r[:cut].decode(errors="ignore") if isinstance(r, (bytes, bytearray)) else str(r)[:cut]
            out[name] = {"ok": True, "data": r}
        else:
            out[name] = {"ok": True, "data": json.dumps(r, default=str)[:cut]}
    except Exception as e:
        out[name] = {"ok": False, "err": repr(e)[:300]}
    print(name, out[name]["ok"])

tryget("fiidii", "/api/fiidiiTradeReact")
tryget("fiidii_nse", "/api/fiidiiTradeNse")
for d in ("23102026", "22102026"):
    tryget(f"part_oi_{d}", f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d}.csv", raw=True)
    tryget(f"part_vol_{d}", f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_vol_{d}.csv", raw=True)
tryget("fii_stats_xls", "https://nsearchives.nseindia.com/content/fo/fii_stats_23-Oct-2026.xls", raw=True, cut=400)
F, T = "01-10-2026", "23-10-2026"
tryget("hist_bulk1", "/api/historicalOR/bulk-block-short-deals", {"optionType": "bulk_deals", "from": F, "to": T})
tryget("hist_block1", "/api/historicalOR/bulk-block-short-deals", {"optionType": "block_deals", "from": F, "to": T})
tryget("hist_bulk2", "/api/historical/bulk-deals", {"from": F, "to": T, "csv": "true"}, raw=True)
tryget("snap", "/api/snapshot-capital-market-largedeal")
json.dump(out, open("probe/out.json", "w"), indent=1)
