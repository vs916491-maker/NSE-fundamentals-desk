import json, sys, os, csv, io, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
from nse import NSE
n = NSE()
n.s.headers["Referer"] = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"
names = collections.Counter(); vals = collections.Counter()
for opt in ("bulk_deals", "block_deals"):
    for F, T in (("01-08-2026", "15-09-2026"), ("16-09-2026", "24-10-2026")):
        t = n.get("/api/historicalOR/bulk-block-short-deals", {"optionType": opt, "from": F, "to": T, "csv": "true"}, raw=True).decode("utf-8-sig", errors="ignore")
        for r in csv.DictReader(io.StringIO(t)):
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            c = r.get("Client Name", "")
            try:
                v = float(r["Quantity Traded"].replace(",", "")) * float(r["Trade Price / Wght. Avg. Price"].replace(",", "")) / 1e7
            except Exception:
                v = 0
            names[c] += 1; vals[c] += v
out = sorted(([c, names[c], round(vals[c], 1)] for c in names), key=lambda x: -x[2])
json.dump({"count": len(out), "names": out}, open("probe/out.json", "w"), indent=0)
