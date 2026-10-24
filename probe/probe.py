"""Probe round 2: integrated-filing results endpoints, full SHP XBRL, quote API, announcement subjects."""
import json, sys, os, re, traceback, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
from nse import NSE

F, T = "20-10-2026", "24-10-2026"
out = {}
n = NSE()

def summ(x):
    if isinstance(x, dict):
        return {"type": "dict", "keys": list(x.keys())[:30],
                **{k: summ(v) for k, v in x.items() if isinstance(v, (list, dict))}}
    if isinstance(x, list):
        return {"type": "list", "len": len(x), "first": x[0] if x else None}
    return str(x)[:300]

def probe(name, path, params=None):
    try:
        out[name] = {"ok": True, "url": path, "params": params, "data": summ(n.get(path, params))}
    except Exception as e:
        out[name] = {"ok": False, "url": path, "params": params, "err": repr(e)[:300]}
    print(name, out[name]["ok"])

IF = "Integrated Filing- Financials"
probe("cfr_nodate", "/api/corporates-financial-results", {"index": "equities", "period": "Quarterly"})
probe("if_1", "/api/integrated-filing-results", {"index": "equities", "type": IF, "period": "Quarterly", "from_date": F, "to_date": T})
probe("if_2", "/api/integrated-filing-results", {"index": "equities", "type": IF})
probe("if_3", "/api/integrated-filing-results", {"index": "equities", "from_date": F, "to_date": T})
probe("if_4", "/api/integrated-filing-results", {"index": "equities", "period_ended": "all", "type": IF})
probe("if_5", "/api/integrated-filing-results", {"index": "equities", "type": "Integrated Filing- Financial", "from_date": F, "to_date": T})
probe("if_6", "/api/corporates-integrated-filing", {"index": "equities", "from_date": F, "to_date": T})
probe("cfr_dates_noperiod", "/api/corporates-financial-results", {"index": "equities", "from_date": F, "to_date": T})
probe("pit2", "/api/corporates-pit", {"index": "equities", "from_date": "01-10-2026", "to_date": T})
probe("sast", "/api/corporate-sast-reg29", {"index": "equities", "from_date": F, "to_date": T})

# quote API with the quote page as referer
try:
    n.s.get("https://www.nseindia.com/get-quotes/equity?symbol=LT", timeout=20)
    n.s.headers["Referer"] = "https://www.nseindia.com/get-quotes/equity?symbol=LT"
    q = n.get("/api/quote-equity", {"symbol": "LT"})
    out["quote_LT"] = {"ok": True, "secinfo": q.get("securityInfo"), "price": q.get("priceInfo", {}).get("lastPrice"),
                       "keys": list(q.keys())}
except Exception as e:
    out["quote_LT"] = {"ok": False, "err": repr(e)[:300]}
n.s.headers["Referer"] = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"

# announcement subjects
try:
    a = n.get("/api/corporate-announcements", {"index": "equities", "from_date": F, "to_date": T})
    out["ann_desc_counts"] = collections.Counter(x.get("desc") for x in a).most_common(120)
    out["ann_orders"] = [x for x in a if re.search(r"order|contract", x.get("desc", ""), re.I)][:8]
    out["ann_penalty"] = [x for x in a if re.search(r"action|penalt|order passed", (x.get("desc", "") + x.get("attchmntText", "")), re.I)][:8]
    out["ann_results"] = [x for x in a if re.search(r"financial result|integrated", (x.get("desc", "") + x.get("attchmntText", "")), re.I)][:6]
except Exception as e:
    out["ann_err"] = repr(e)

# full SHP XBRL facts
try:
    sh = n.get("/api/corporate-share-holdings-master", {"index": "equities", "from_date": F, "to_date": T})
    out["sh_first"] = sh[0]
    x = n.get(sh[0]["xbrl"], raw=True).decode(errors="ignore")
    facts = re.findall(r'<(in-bse-shp:\w+)[^>]*contextRef="([^"]+)"[^>]*>([^<]{0,40})<', x)
    out["sh_facts"] = [f for f in facts if re.search(r"Percent|Total|Number", f[0])][:400]
except Exception as e:
    out["sh_err"] = repr(e)

json.dump(out, open("probe/out.json", "w"), indent=1, default=str)
