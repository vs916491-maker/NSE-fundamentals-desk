"""Temporary probe (removed before merge): run collector/history.py for a few stocks and dump the results."""
import os, sys, json, time, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
import run, fundamentals, history
from datetime import date
SAMPLE = ["WABAG", "HDFCBANK", "BAJFINANCE", "NAUKRI", "HFCL", "CONCOR", "TCS", "BSE"]
tmp = tempfile.mkdtemp()
c = run.Collector(budget_min=30)
c.load_close(date.today())
f = fundamentals.Fund(c, run.DATA, run.CACHE, run.jload, run.jsave, run.parse_nse_date)
f.rows = {s: f.rows[s] for s in SAMPLE if s in f.rows}
t0 = time.time()
history.update(f, tmp, minutes=14)
print("TIME", round(time.time() - t0))
ca = run.jload(os.path.join(tmp, "corp_actions.json"), {})
print("CAN", len(ca.get("a", {})))
idx = run.jload(os.path.join(tmp, "px", "index.json"), {})
print("IDX", json.dumps(idx))
px = {}
for q in idx.get("q", []):
    for s in SAMPLE:
        j = run.jload(os.path.join(tmp, "px", q, history._shard(s) + ".json"), {})
        if s in (j.get("p") or {}):
            px.setdefault(s, {"d": [], "p": []})
            px[s]["d"] += j["d"]; px[s]["p"] += j["p"][s]
for s in SAMPLE:
    r = f.rows.get(s, {})
    print("DUMP " + json.dumps({"sym": s, "eh": r.get("eh"), "ca": ca.get("a", {}).get(s), "px": px.get(s)}, separators=(",", ":")))
