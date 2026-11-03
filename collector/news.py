"""Market news: headlines from business-news RSS feeds, merged, ranked by market-driving themes.

Writes site/data/news.json. Run hourly by .github/workflows/news.yml.
Only headlines, a short feed snippet and the link are kept; the article stays on the publisher's site.

  python collector/news.py           # skip if updated in the last 40 minutes
  python collector/news.py --force
"""
import argparse, html, json, logging, os, re, sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote
import xml.etree.ElementTree as ET

log = logging.getLogger("news")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "site", "data", "news.json")
KEEP_HOURS = 48
MAX_KEY = 30
IST = timezone(timedelta(hours=5, minutes=30))


def gnews(q):
    return f"https://news.google.com/rss/search?q={quote(q)}&hl=en-IN&gl=IN&ceid=IN:en"


# (key, url, source name or None for Google News, default group)
FEEDS = [
    ("et_markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "Economic Times", "in_mkt"),
    ("et_economy", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms", "Economic Times", "in_eco"),
    ("mint_markets", "https://www.livemint.com/rss/markets", "Mint", "in_mkt"),
    ("mint_economy", "https://www.livemint.com/rss/economy", "Mint", "in_eco"),
    ("bs_markets", "https://www.business-standard.com/rss/markets-106.rss", "Business Standard", "in_mkt"),
    ("bs_economy", "https://www.business-standard.com/rss/economy-102.rss", "Business Standard", "in_eco"),
    ("mc_markets", "https://www.moneycontrol.com/rss/marketreports.xml", "Moneycontrol", "in_mkt"),
    ("mc_economy", "https://www.moneycontrol.com/rss/economy.xml", "Moneycontrol", "in_eco"),
    ("cnbc_top", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC", "global"),
    ("cnbc_economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html", "CNBC", "global"),
    ("cnbc_markets", "https://www.cnbc.com/id/15839135/device/rss/rss.html", "CNBC", "global"),
    ("cnbc_world", "https://www.cnbc.com/id/100727362/device/rss/rss.html", "CNBC", "global"),
    ("mw_top", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "MarketWatch", "global"),
    ("g_rbi", gnews("RBI OR \"repo rate\" OR \"monetary policy\" India when:2d"), None, "in_eco"),
    ("g_india_macro", gnews("India inflation OR GDP OR \"fiscal deficit\" OR \"GST collection\" when:2d"), None, "in_eco"),
    ("g_fii", gnews("FII OR FPI India equities outflow OR inflow when:2d"), None, "in_mkt"),
    ("g_rupee", gnews("rupee dollar OR \"bond yield\" India when:2d"), None, "in_mkt"),
    ("g_nifty", gnews("Sensex Nifty market today when:1d"), None, "in_mkt"),
    ("g_fed", gnews("\"Federal Reserve\" OR Powell OR FOMC OR \"Fed rate\" when:2d"), None, "global"),
    ("g_us_macro", gnews("US jobs report OR payrolls OR \"US inflation\" OR \"US GDP\" when:2d"), None, "global"),
    ("g_wallst", gnews("\"Wall Street\" OR \"S&P 500\" OR Nasdaq stocks when:1d"), None, "global"),
    ("g_crude", gnews("crude oil prices Brent OPEC when:2d"), None, "global"),
]

# publishers kept from Google News (others are often aggregators or AI rewrites)
TRUSTED = {
    "reuters": "Reuters", "bloomberg": "Bloomberg", "wsj": "WSJ", "wall street journal": "WSJ", "cnbc": "CNBC",
    "financial times": "Financial Times", "ft.com": "Financial Times", "the economic times": "Economic Times",
    "economic times": "Economic Times", "livemint": "Mint", "mint": "Mint", "business standard": "Business Standard",
    "moneycontrol": "Moneycontrol", "the times of india": "Times of India", "times of india": "Times of India",
    "the hindu businessline": "BusinessLine", "businessline": "BusinessLine", "the hindu": "The Hindu",
    "financial express": "Financial Express", "the financial express": "Financial Express", "ndtv profit": "NDTV Profit",
    "ndtv": "NDTV", "marketwatch": "MarketWatch", "barron's": "Barron's", "barrons": "Barron's", "associated press": "AP",
    "ap news": "AP", "yahoo finance": "Yahoo Finance", "investing.com": "Investing.com", "cnn": "CNN", "bbc": "BBC",
    "the new york times": "NYT", "fortune": "Fortune", "axios": "Axios", "business today": "Business Today",
    "india today": "India Today", "hindustan times": "Hindustan Times", "press trust of india": "PTI", "pti": "PTI",
    "zee business": "Zee Business", "cnbc tv18": "CNBC-TV18", "cnbctv18": "CNBC-TV18", "cnbc-tv18": "CNBC-TV18",
    "the indian express": "Indian Express", "indian express": "Indian Express", "nikkei asia": "Nikkei Asia",
    "s&p global": "S&P Global", "kiplinger": "Kiplinger", "the wall street journal": "WSJ",
}
TIER1 = {"Reuters", "Bloomberg", "WSJ", "Financial Times", "CNBC", "Economic Times", "Mint", "Business Standard",
         "Moneycontrol", "BusinessLine", "Financial Express", "MarketWatch", "NDTV Profit", "CNBC-TV18", "AP", "PTI"}

GROUP_LABEL = {"in_eco": "India economy", "in_mkt": "India markets", "global": "US & global"}

# theme -> (group, weight, pattern)
THEMES = [
    ("RBI & rates", "in_eco", 3.0, r"\brbi\b|reserve bank of india|repo rate|\bmpc\b|monetary policy committee|\bcrr\b|rate (hike|cut).{0,30}india|india.{0,30}rate (hike|cut)"),
    ("India inflation", "in_eco", 2.5, r"(\bcpi\b|\bwpi\b|inflation|food prices).{0,60}(india|retail|wholesale)|(india|retail|wholesale).{0,60}(\bcpi\b|\bwpi\b|inflation)"),
    ("Growth & GDP", "in_eco", 2.5, r"\bgdp\b|\biip\b|\bpmi\b|core sector|industrial output|growth (forecast|estimate|outlook)|economic growth"),
    ("Fiscal & policy", "in_eco", 2.0, r"budget|fiscal deficit|gst collection|\bgst\b|\bltcg\b|\bstt\b|capital gains tax|disinvestment|finance ministry|\bsebi\b"),
    ("Trade & tariffs", "in_eco", 2.5, r"tariff|trade (deal|pact|talks|war|deficit)|exports?\b|imports?\b|\bfta\b"),
    ("FII / DII flows", "in_mkt", 3.0, r"\bfiis?\b|\bfpis?\b|foreign (portfolio )?investors?|foreign (fund|money)|\bdiis?\b|outflows?|inflows?"),
    ("Sensex & Nifty", "in_mkt", 2.0, r"\bsensex\b|\bnifty\b|dalal street|stock market today|market (close|wrap|today)|closing bell|opening bell"),
    ("Rupee & bonds", "in_mkt", 2.5, r"\brupee\b|bond yields?|\bg-?secs?\b|10-year (yield|bond)|government bonds?"),
    ("Big results", "in_mkt", 1.5, r"\b(sbi|reliance|hdfc bank|icici bank|infosys|\btcs\b|l&t|larsen|itc|bharti airtel|kotak|axis bank|maruti|tata motors|bajaj finance|hul|hindustan unilever|ongc|ntpc|adani)\b.{0,60}(q[1-4]|results|profit|earnings)"),
    ("Fed & US rates", "global", 3.0, r"federal reserve|\bthe fed\b|\bfed\b|powell|\bfomc\b|treasury yields?|10-year treasury"),
    ("US economy", "global", 2.5, r"jobs report|payrolls|jobless claims|unemployment rate|(us|u\.s\.).{0,30}(inflation|cpi|gdp|retail sales|consumer)|consumer (confidence|sentiment)"),
    ("Wall Street", "global", 2.0, r"wall street|s&p 500|\bnasdaq\b|\bdow\b|dow jones|us stocks|u\.s\. stocks|stock futures"),
    ("Crude & commodities", "global", 2.5, r"\bcrude\b|\boil prices?\b|\bbrent\b|\bopec\b|\bgold prices?\b|\bwti\b"),
    ("Geopolitics", "global", 2.0, r"\bwar\b|strikes?\b.{0,20}(iran|israel|gaza|ukraine|russia)|\biran\b|\bisrael\b|\bukraine\b|\brussia\b|sanctions|ceasefire|missile"),
    ("Global central banks", "global", 1.5, r"\becb\b|bank of japan|\bboj\b|bank of england|\bpboc\b|central bank.{0,30}(hike|cut|rates?)|rates? to .{0,20}high"),
    ("Dollar", "global", 1.5, r"dollar index|\bdxy\b|greenback|dollar (rises|falls|slips|gains|strengthens|weakens)"),
    ("Big Tech & AI", "global", 1.0, r"\b(nvidia|apple|microsoft|alphabet|google|amazon|meta|tesla|palantir|openai|anthropic)\b"),
]
THEMES_RX = [(n, g, w, re.compile(p, re.I)) for n, g, w, p in THEMES]
INDIA_RX = re.compile(r"\bindia|\brbi\b|sensex|nifty|rupee|\bsebi\b|dalal|mumbai|delhi|\bnse\b|\bbse\b|crore|lakh|\bgst\b|"
                      r"sitharaman|goyal|\bfiis?\b|\bfpis?\b|\bdiis?\b|\bmcx\b", re.I)
# stock tips and listicles are not market drivers
NOISE_RX = re.compile(r"stocks? to (buy|watch|sell)|target,? stop[- ]loss|multibagger|should you (buy|sell)|penny stock|"
                      r"top (gainers|losers)|buy or sell|technical (view|picks)|share price (today|live)|stock picks|"
                      r"\bipo\b.{0,40}(gmp|subscription status|allotment)|horoscope|lottery|fd (interest )?rates|"
                      r"small-cap stock|mid-cap stock|\bkya\b|hindi|prediction|support,? (and )?resistance|expiry today|"
                      r"currency notes|rs 10, rs 20|fact check|how much (more )?will you earn|which banks? (give|offer)|\blive( updates|:)|"
                      r"trade setup|market outlook today|ahead of (diwali|dhanteras)", re.I)
GLOBAL_CTX = re.compile(r"\b(us|u\.s\.|america|europe|european|eurozone|china|japan|global|world|wall street|fed|treasury)\b", re.I)
STOP = set("a an the of to in on for and or as at by with from is are be after amid over vs its it this that today "
           "says said may will what why how new".split())


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def parse_items(raw: bytes):
    """RSS <item>s as dicts; falls back to a regex read for feeds with broken XML (Moneycontrol)."""
    try:
        root = ET.fromstring(raw)
        out = []
        for i in root.findall(".//item"):
            src = i.find("source")
            out.append({"title": i.findtext("title") or "", "link": i.findtext("link") or "",
                        "date": i.findtext("pubDate") or "", "desc": i.findtext("description") or "",
                        "src": (src.text if src is not None else None)})
        return out
    except ET.ParseError:
        text = raw.decode("utf-8", errors="ignore")
        out = []
        for block in re.findall(r"<item>(.*?)</item>", text, re.S):
            def tag(t):
                m = re.search(rf"<{t}[^>]*>(.*?)</{t}>", block, re.S)
                return re.sub(r"^<!\[CDATA\[|\]\]>$", "", (m.group(1) if m else "").strip())
            out.append({"title": tag("title"), "link": tag("link"), "date": tag("pubDate"), "desc": tag("description"), "src": None})
        return out


SYN = {"pts": "points", "pt": "points", "nifty50": "nifty", "rises": "up", "rise": "up", "jumps": "up", "jump": "up",
       "gains": "up", "surges": "up", "rallies": "up", "climbs": "up", "soars": "up", "falls": "down", "fall": "down",
       "drops": "down", "slips": "down", "tumbles": "down", "declines": "down", "sinks": "down", "plunges": "down",
       "hikes": "hike", "cuts": "cut", "raises": "hike", "rbi's": "rbi", "fed's": "fed", "u.s.": "us"}


def norm_tokens(title):
    t = re.sub(r"(?<=\d),(?=\d)", "", title.lower())          # 1,000 -> 1000
    words = re.findall(r"[a-z0-9&%.']+", t)
    out = set()
    for w in words:
        w = SYN.get(w.strip(".'"), w.strip(".'"))
        if w not in STOP and (len(w) > 2 or w in ("up", "us")):
            out.add(w)
    return out


def fetch_all(session):
    items = []
    for key, url, srcname, group in FEEDS:
        try:
            r = session.get(url, timeout=25)
            if r.status_code != 200:
                log.warning("%s: HTTP %s", key, r.status_code)
                continue
            got = 0
            for it in parse_items(r.content):
                title = clean(it["title"])
                if not title or not it["link"]:
                    continue
                src = srcname
                if src is None:  # Google News: "Headline - Publisher" plus a <source> tag
                    pub = clean(it.get("src") or (title.rsplit(" - ", 1)[1] if " - " in title else ""))
                    src = TRUSTED.get(pub.lower())
                    if not src:
                        continue
                    if " - " in title:
                        title = title.rsplit(" - ", 1)[0].strip()
                try:
                    ts = parsedate_to_datetime(it["date"]).astimezone(timezone.utc)
                except Exception:
                    continue
                desc = "" if srcname is None else clean(it["desc"])[:220]
                items.append({"t": title, "u": it["link"].strip(), "src": src, "ts": ts.isoformat(timespec="minutes"),
                              "desc": desc, "feed_group": group})
                got += 1
            log.info("%s: %d items", key, got)
        except Exception as e:
            log.warning("%s: %s", key, e)
    return items


def score_item(it, now):
    text = f"{it['t']} {it.get('desc', '')}"
    hits = [(n, g, w) for n, g, w, rx in THEMES_RX if rx.search(text)]
    # title-only matches count fully, snippet-only matches count half
    best, themes, group = 0.0, [], None
    for n, g, w in hits:
        in_title = any(rx.search(it["t"]) for nn, gg, ww, rx in THEMES_RX if nn == n)
        w_eff = w if in_title else w / 2
        themes.append(n)
        if w_eff > best:
            best, group = w_eff, g
    score = best + 0.5 * max(0, len(themes) - 1)
    if NOISE_RX.search(it["t"]):
        score -= 3
    age_h = (now - datetime.fromisoformat(it["ts"])).total_seconds() / 3600
    score += 1.0 if age_h <= 6 else 0.5 if age_h <= 18 else 0
    if it["src"] in TIER1:
        score += 0.5
    if group is None:
        group = it["feed_group"]
    # an "India" theme in a story with no Indian angle but a foreign one (e.g. Europe's bond yields) is global news
    if group != "global" and not INDIA_RX.search(text) and GLOBAL_CTX.search(text):
        group = "global"
    # a global theme in an Indian story (e.g. crude and India's import bill) stays global; India-only themes need India
    title_hit = any(rx.search(it["t"]) for _, _, _, rx in THEMES_RX)
    return round(score, 2), themes, group, title_hit


def cluster(items):
    """Merge headlines about the same story (shared-word overlap)."""
    items.sort(key=lambda x: x["ts"], reverse=True)
    groups = []
    for it in items:
        tok = norm_tokens(it["t"])
        if not tok:
            continue
        ts = datetime.fromisoformat(it["ts"])
        for g in groups:
            inter = len(tok & g["tok0"])
            if (inter >= 4 and inter / min(len(tok), len(g["tok0"])) >= 0.55
                    and abs((g["ts"] - ts).total_seconds()) <= 18 * 3600):
                g["members"].append(it)
                g["tok"] |= tok
                break
        else:
            groups.append({"tok": set(tok), "tok0": set(tok), "ts": ts, "members": [it]})
    return groups


def build(raw_items, prev_items, now):
    seen, merged = set(), []
    for it in raw_items + prev_items:
        k1, k2 = it.get("u") or "", (it["src"], it["t"].lower())
        if k1 in seen or k2 in seen:
            continue
        seen.add(k1)
        seen.add(k2)
        if now - datetime.fromisoformat(it["ts"]) > timedelta(hours=KEEP_HOURS):
            continue
        it.setdefault("feed_group", {"India economy": "in_eco", "India markets": "in_mkt"}.get(it.get("group"), "global"))
        merged.append(it)
    out = []
    for g in cluster(merged):
        mem = g["members"]
        sources = []
        for m in mem:
            if m["src"] not in sources:
                sources.append(m["src"])
        # lead: a top-tier source if there is one, else the earliest report
        lead = sorted(mem, key=lambda m: (m["src"] not in TIER1, m["ts"]))[0]
        sc, themes, group, title_hit = score_item(lead, now)
        for m in mem:  # themes found in any version of the story count
            _, th, _, th_hit = score_item(m, now)
            themes += [t for t in th if t not in themes]
            title_hit = title_hit or th_hit
        sc += min(3.0, 0.75 * (len(sources) - 1))
        out.append({"t": lead["t"], "u": lead["u"], "src": lead["src"], "ts": max(m["ts"] for m in mem),
                    "desc": lead.get("desc", ""), "group": GROUP_LABEL[group], "themes": themes[:4], "score": round(sc, 2),
                    "key": sc >= 4.0 and title_hit,
                    "also": [[m["src"], m["u"]] for m in mem if m is not lead and m["src"] != lead["src"]][:6]})
    keys = sorted([o for o in out if o["key"]], key=lambda o: (-o["score"], o["ts"]))
    for o in keys[MAX_KEY:]:  # keep the key-driver list short
        o["key"] = False
    keys = keys[:MAX_KEY]
    rest = sorted([o for o in out if not o["key"]], key=lambda o: o["ts"], reverse=True)
    return keys + rest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    now = datetime.now(timezone.utc)
    prev = {}
    try:
        with open(OUT) as f:
            prev = json.load(f)
    except Exception:
        pass
    if not a.force and prev.get("updated"):
        age = now - datetime.fromisoformat(prev["updated"])
        if age < timedelta(minutes=40):
            log.info("news updated %d minutes ago; skipping", age.total_seconds() // 60)
            return
    from curl_cffi import requests
    s = requests.Session(impersonate="chrome")
    raw = fetch_all(s)
    if len(raw) < 20:
        log.error("only %d headlines fetched; keeping the previous file", len(raw))
        sys.exit(0)
    # earlier headlines that have dropped off the feeds are kept for 48 hours (sources merged again from scratch)
    prev_items = []
    for o in prev.get("items", []):
        prev_items.append({"t": o["t"], "u": o["u"], "src": o["src"], "ts": o["ts"], "desc": o.get("desc", ""),
                           "group": o.get("group")})
        for src, u in o.get("also", []):
            prev_items.append({"t": o["t"], "u": u, "src": src, "ts": o["ts"], "desc": "", "group": o.get("group")})
    items = build(raw, prev_items, now)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT + ".tmp", "w") as f:
        json.dump({"updated": now.isoformat(timespec="minutes"), "items": items}, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(OUT + ".tmp", OUT)
    log.info("news: %d stories (%d key drivers) from %d headlines", len(items), sum(o["key"] for o in items), len(raw))


if __name__ == "__main__":
    main()
