"""Probe round 3: integrated filing paging + financial XBRL facts; SHP by symbol; bhavcopy."""
import json, sys, os, re, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
from nse import NSE

F, T = "20-10-2026", "24-10-2026"
IF = "Integrated Filing- Financials"
out = {}
n = NSE()

def lens(params):
    try:
        r = n.get("/api/integrated-filing-results", params)
        d = r.get("data") or []
        return {"len": len(d), "meta": {k: r.get(k) for k in ("size", "page", "totalCount")},
                "first_sym": d[0]["symbol"] if d else None, "last_sym": d[-1]["symbol"] if d else None,
                "qe": collections.Counter(x.get("qe_Date") for x in d).most_common(5)}
    except Exception as e:
        return repr(e)[:200]

base = {"index": "equities", "type": IF, "from_date": F, "to_date": T}
out["page1"] = lens(base)
out["page2"] = lens({**base, "page": 2})
out["size100"] = lens({**base, "size": 100})
out["size100_p2"] = lens({**base, "size": 100, "page": 2})
out["pageNo2"] = lens({**base, "pageNo": 2})

# collect a Q2 FY27 financials filing for an Ind-AS non-bank and a bank, dump XBRL facts
allrows = []
for p in range(1, 6):
    try:
        r = n.get("/api/integrated-filing-results", {**base, "size": 100, "page": p})
        allrows += r.get("data") or []
    except Exception:
        break
out["collected"] = len(allrows)
q2 = [x for x in allrows if x.get("qe_Date") == "30-SEP-2026" and x.get("xbrl")]
out["q2_count"] = len(q2)
out["q2_samples"] = q2[:3]
picked = []
for want in ("INDAS", "BANK", "NBFC"):
    for x in q2:
        if want in x["xbrl"].upper() and x not in picked:
            picked.append(x); break
if not picked and q2:
    picked = q2[:2]
out["xbrl_docs"] = {}
for x in picked[:3]:
    try:
        doc = n.get(x["xbrl"], raw=True).decode(errors="ignore")
        ctx = {}
        for m in re.finditer(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', doc, re.S):
            sd = re.search(r"<xbrli:startDate>([^<]+)", m.group(2)); ed = re.search(r"<xbrli:endDate>([^<]+)", m.group(2))
            inst = re.search(r"<xbrli:instant>([^<]+)", m.group(2))
            dims = re.findall(r'dimension="([^"]+)">([^<]+)<', m.group(2))
            ctx[m.group(1)] = [sd and sd.group(1), ed and ed.group(1), inst and inst.group(1), dims]
        facts = re.findall(r'<([\w-]+:\w+)[^>]*contextRef="([^"]+)"[^>]*>([^<]{0,60})<', doc)
        keep = [f for f in facts if re.search(r"Revenue|Income|Profit|Earnings|Expense|Tax|Whether|Type|Nature|Date|Level|Segment", f[0], re.I)]
        out["xbrl_docs"][x["symbol"] + "|" + x["xbrl"]] = {"contexts": ctx, "facts": keep[:250], "len": len(doc)}
    except Exception as e:
        out["xbrl_docs"][x["symbol"]] = repr(e)

# SHP by symbol
try:
    r = n.get("/api/corporate-share-holdings-master", {"index": "equities", "symbol": "LT"})
    out["shp_LT"] = {"len": len(r), "first": r[:2]}
except Exception as e:
    out["shp_LT"] = repr(e)[:200]
# bhavcopy
try:
    b = n.get("https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_23102026.csv", raw=True).decode()
    out["bhav"] = b[:500]
except Exception as e:
    out["bhav"] = repr(e)[:200]

json.dump(out, open("probe/out.json", "w"), indent=1, default=str)
