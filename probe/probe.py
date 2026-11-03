import json, sys, re, time
import xml.etree.ElementTree as ET
from urllib.parse import quote
from curl_cffi import requests
S = requests.Session(impersonate="chrome")
G = lambda q: f"https://news.google.com/rss/search?q={quote(q)}&hl=en-IN&gl=IN&ceid=IN:en"
FEEDS = {
 "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
 "et_economy": "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
 "et_stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
 "mc_markets": "https://www.moneycontrol.com/rss/marketreports.xml",
 "mc_economy": "https://www.moneycontrol.com/rss/economy.xml",
 "mc_business": "https://www.moneycontrol.com/rss/business.xml",
 "mint_markets": "https://www.livemint.com/rss/markets",
 "mint_economy": "https://www.livemint.com/rss/economy",
 "bs_markets": "https://www.business-standard.com/rss/markets-106.rss",
 "bs_economy": "https://www.business-standard.com/rss/economy-102.rss",
 "cnbc_top": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
 "cnbc_economy": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
 "cnbc_markets": "https://www.cnbc.com/id/15839135/device/rss/rss.html",
 "cnbc_world": "https://www.cnbc.com/id/100727362/device/rss/rss.html",
 "mw_top": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
 "mw_pulse": "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
 "g_rbi": G("RBI OR repo rate OR monetary policy India when:2d"),
 "g_fed": G("Federal Reserve OR Fed rate OR Powell when:2d"),
 "g_nifty": G("Sensex OR Nifty when:1d"),
 "g_wallst": G("Wall Street OR \"S&P 500\" OR Nasdaq when:1d"),
}
out = {}
for k, u in FEEDS.items():
    try:
        r = S.get(u, timeout=25, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128 Safari/537.36"})
        info = {"status": r.status_code, "bytes": len(r.content)}
        try:
            root = ET.fromstring(r.content)
            items = root.findall(".//item")
            info["items"] = len(items)
            info["sample"] = [{"t": (i.findtext("title") or "")[:140], "d": i.findtext("pubDate"), "src": i.findtext("source"),
                               "desc": re.sub("<[^>]+>", "", i.findtext("description") or "")[:160], "link": (i.findtext("link") or "")[:120]} for i in items[:3]]
        except Exception as e:
            info["parse"] = repr(e)[:120]; info["head"] = r.text[:200]
    except Exception as e:
        info = {"err": repr(e)[:200]}
    out[k] = info; print(k, info.get("status"), info.get("items"), info.get("err") or info.get("parse") or "")
json.dump(out, open("probe/out.json", "w"), indent=1)
