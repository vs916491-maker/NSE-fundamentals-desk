"""Policy and Budget news by theme, for the Stock page ("Policy & Budget watch").

For each topic below (a theme from themes.csv, or a narrower slice of one such as water or railways)
this searches Google News for government-policy headlines, keeps the ones from known publishers
whose headline mentions both the topic and a policy action (Budget, Cabinet approval, scheme, PLI,
duty, allocation...), and writes site/data/policy.json. Headlines already collected for the News tab
are scanned too. Headlines are kept for KEEP_DAYS because policy news is sparse.

Each headline gets a rough "tailwind" / "headwind" guess from its wording. It is keyword matching,
not analysis: it reads the headline only, cannot tell how big the effect is, and will be wrong at
times. The Stock page says so.

  python collector/policy.py           # skip if updated in the last 10 hours
  python collector/policy.py --force

Edit TOPICS to add a scheme name or move an industry. "themes" = every stock in that theme sees the
topic; "inds" = only stocks with that NSE basic industry (names as in cache/industry.json).
"""
import argparse, json, logging, os, re, sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import news

log = logging.getLogger("policy")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "site", "data", "policy.json")
KEEP_DAYS = 75
MAX_PER_TOPIC = 15
SKIP_HOURS = 10

# name, themes, inds, search words (Google News), headline pattern
TOPICS = [
    ("Power & grid", ["Power & grid"], [], "power sector OR electricity OR discom OR transmission",
     r"power (sector|ministry|plants?|capacity|demand|tariffs?)|electricity|discoms?|transmission (lines?|projects?|capex)|thermal power|\bgrid\b|smart meters?|\brdss\b|\bcea\b|nuclear power|energy storage|\bbess\b|pumped storage"),
    ("Renewable energy", ["Power & grid"], [], "solar OR \"renewable energy\" OR \"green hydrogen\" OR wind energy",
     r"\bsolar\b|renewables?|green hydrogen|wind (energy|power)|\bmnre\b|pm surya ghar|\bkusum\b|\balmm\b|rooftop|\bseci\b"),
    ("Defence", ["Defence & aerospace"], [], "defence ministry OR \"defence procurement\" OR DAC OR \"defence exports\"",
     r"defen[cs]e|\bdac\b|\bdrdo\b|\bhal\b|indigeni[sz]ation|warships?|fighter jets?|missiles?|\bnavy\b|air force|\barmy\b"),
    ("Shipbuilding", [], ["Ship Building & Allied Services", "Shipping"], "shipbuilding policy OR \"maritime development fund\"",
     r"ship ?building|shipyards?|maritime (development|fund|policy)|shipping (ministry|policy|sector)"),
    ("Railways", ["Railways"], ["Railway Wagons"], "railways budget OR \"railway capex\" OR Vande Bharat OR \"rail ministry\" OR wagons",
     r"railways?|\brail\b|vande bharat|kavach|freight corridors?|wagons?|\bmetro\b|bullet train|\brrts\b|amrit bharat"),
    ("Roads & highways", [], ["Civil Construction", "Road Assets - Toll Annuity Hybrid-Annuity", "Construction Vehicles"],
     "highways OR NHAI OR \"road ministry\" OR expressway",
     r"highways?|\bnhai\b|\bmorth\b|expressways?|road (ministry|projects?|construction|sector)|\bbharatmala\b|toll"),
    ("Infrastructure capex", ["Infrastructure & construction", "Cement & building materials", "Capital goods & industrials"], [],
     "infrastructure capex OR \"capital expenditure\" government OR \"National Infrastructure Pipeline\"",
     r"infrastructure|infra (push|spend|capex|projects?)|capital expenditure|\bcapex\b|gati shakti|national infrastructure pipeline|\bnip\b|smart cities"),
    ("Water & sanitation", [], ["Water Supply & Management", "Waste Management"],
     "\"Jal Jeevan\" OR AMRUT OR \"water supply\" OR sewage OR \"Namami Gange\" OR desalination",
     r"jal jeevan|\bamrut\b|water (supply|treatment|projects?|infrastructure|sector)|drinking water|sewage|sewerage|waste ?water|namami gange|desalination|river (linking|cleaning)|jal shakti|swachh bharat|solid waste|sanitation"),
    ("Ports & airports", [], ["Port & Port services", "Airport & Airport services", "Dredging", "Airline"],
     "ports OR sagarmala OR airports OR \"civil aviation\" policy",
     r"\bports?\b|sagarmala|airports?|civil aviation|\budan\b|dredging"),
    ("Housing & real estate", ["Real estate"], ["Housing Finance Company", "Paints", "Plywood Boards/ Laminates", "Ceramics", "Sanitary Ware"],
     "housing OR \"real estate\" OR PMAY OR RERA OR \"affordable housing\"",
     r"housing|real estate|realty|\bpmay\b|\brera\b|home ?buyers?|home loans?|stamp duty|affordable homes?"),
    ("Cement & building materials", ["Cement & building materials"], [], "cement industry OR \"cement prices\" OR \"cement demand\"",
     r"\bcement\b|building materials?|\btiles\b"),
    ("Capital goods & manufacturing", ["Capital goods & industrials"], [], "\"capital goods\" OR \"Make in India\" OR \"manufacturing mission\" OR PLI manufacturing",
     r"capital goods|make in india|manufacturing (mission|sector|push|hub|policy)|\bpli\b|production[- ]linked|\bqcos?\b|quality control orders?|\bmsmes?\b"),
    ("Electronics & semiconductors", ["Electronics & telecom equipment"], ["Consumer Electronics", "Household Appliances"],
     "electronics manufacturing OR semiconductor OR ECMS OR \"India Semiconductor Mission\"",
     r"electronics|semiconductors?|\bchips?\b|\becms\b|\bism\b|mobile (phone )?(manufactur|export)|\bmeity\b|display fab|components? scheme|telecom (equipment|gear)|data cent(re|er)s?"),
    ("IT & digital", ["IT & software"], [], "IT sector OR H-1B OR \"data protection\" OR \"IndiaAI\" OR \"data centre\" policy",
     r"\bit (sector|services|firms|companies|exports)|h-?1b|visa (fee|rules?|curbs?)|data protection|\bdpdp\b|indiaai|artificial intelligence|\bai (mission|policy|rules)|data cent(re|er)s?|software exports?|outsourcing|\bgccs?\b"),
    ("Banks", ["Banks"], [], "banks RBI norms OR \"bank credit\" OR \"PSU banks\" OR \"bank recapitalisation\"",
     r"\bbanks?\b|banking|\bpsbs?\b|credit growth|\bnpas?\b|deposit (rates?|insurance)|priority sector|\bcrr\b|liquidity (norms|coverage)|lending (rates?|norms)"),
    ("NBFCs & lenders", ["Lenders (NBFC & housing finance)"], [], "NBFC RBI norms OR microfinance OR \"gold loan\" rules OR \"housing finance\"",
     r"\bnbfcs?\b|shadow banks?|microfinance|\bmfis?\b|gold loans?|housing finance|risk weights?|co-?lending|digital lending|unsecured loans?"),
    ("Capital markets & insurance", ["Capital markets & insurance"], [], "SEBI rules OR \"mutual fund\" regulations OR IRDAI OR \"insurance FDI\" OR STT",
     r"\bsebi\b|mutual funds?|\bamcs?\b|brokers?|broking|f&o (curbs|rules|norms)|derivatives? (curbs|rules|norms)|\bstt\b|\birdai\b|insurance|insurers?|capital gains|\bltcg\b|\bfintechs?\b|\bupi\b|\bmdr\b|stock exchanges?"),
    ("Pharma & healthcare", ["Pharma & healthcare"], ["Pharmacy Retail"], "pharma OR NPPA OR \"drug prices\" OR \"Ayushman Bharat\" OR \"health budget\" OR USFDA tariff pharma",
     r"pharma|\bdrugs?\b|medicines?|\bnppa\b|\bnlem\b|ayushman|health (budget|ministry|sector|insurance|mission)|healthcare|hospitals?|medical devices?|\bcdsco\b|bulk drugs?|\bapis?\b|generics?|vaccines?|biosimilars?"),
    ("Auto & EVs", ["Auto & auto parts"], [], "auto industry OR \"electric vehicles\" OR \"PM E-Drive\" OR \"scrappage policy\" OR CAFE norms",
     r"\bautos?\b|automobiles?|automakers?|carmakers?|\bevs?\b|electric (vehicles?|two-wheelers?|buses|mobility)|pm e-?drive|\bfame\b|scrappage|\bcafe\b|emission norms|\bbs-?vii?\b|two-wheelers?|tractors?|tyres?|ethanol blend|\be20\b|battery (swapping|manufactur)|\bacc\b|charging (infra|stations?)|rare earth"),
    ("FMCG & rural demand", ["Consumer staples (FMCG)"], [], "FMCG OR \"rural demand\" OR MSP hike OR MGNREGA OR \"food processing\" scheme",
     r"\bfmcg\b|rural (demand|consumption|spending|economy)|\bmsp\b|\bmgnrega\b|pm[- ]kisan|food processing|consumption (boost|push|demand)|packaged foods?|tobacco|cigarettes?|sin goods|income tax (cut|relief|slab)|pay commission"),
    ("Sugar & ethanol", [], ["Sugar", "Breweries & Distilleries"], "sugar OR ethanol policy OR FRP OR \"sugar MSP\" OR \"sugar exports\"",
     r"\bsugar\b|sugarcane|ethanol|\bfrp\b|molasses|liquor|alcohol|excise policy"),
    ("Edible oil & agri", [], ["Edible Oil", "Other Agricultural Products", "Tea & Coffee", "Dairy Products", "Seafood", "Animal Feed", "Meat Products including Poultry"],
     "edible oil import duty OR \"oilseeds mission\" OR agriculture exports OR dairy OR seafood exports",
     r"edible oils?|palm oil|oilseeds?|soy(a|bean)|agri(culture)? (exports?|budget|ministry|credit|infrastructure)|\bdairy\b|seafood|shrimp|fisheries|\btea\b|coffee|poultry|\brice\b|\bwheat\b"),
    ("Consumer durables & retail", ["Consumer durables & retail"], [], "consumer durables OR \"gold import duty\" OR e-commerce policy OR retail FDI OR \"GST rate\" appliances",
     r"consumer durables?|appliances?|air ?conditioners?|\bacs\b|gold (import|duty|hallmark|loan|monetisation)|jewell?ery|e-?commerce|quick commerce|retail(ers)? (fdi|policy|trade)|footwear|toys?|furniture|paints?"),
    ("Travel & hospitality", ["Travel & leisure"], [], "tourism policy OR hotels \"infrastructure status\" OR \"civil aviation\" OR \"e-visa\"",
     r"tourism|tourists?|hotels?|hospitality|aviation|airlines?|airfares?|\bvisas?\b|\budan\b|restaurants?"),
    ("Logistics & shipping", ["Logistics & shipping"], [], "logistics policy OR \"dedicated freight corridor\" OR shipping OR \"multimodal logistics\"",
     r"logistics|freight|shipping|warehous|cargo|containers?|multimodal|e-?way bill|inland waterways?|coastal shipping"),
    ("Chemicals", ["Chemicals"], [], "chemicals \"anti-dumping duty\" OR \"chemical industry\" policy OR petrochemicals PCPIR",
     r"chemicals?|petrochem|anti-?dumping|\bdgtr\b|soda ash|caustic soda|\bpvc\b|carbon black|dyes?|explosives?"),
    ("Fertilisers & agrochemicals", ["Fertilisers & agrochemicals"], [], "fertiliser subsidy OR urea OR DAP OR \"nutrient based subsidy\" OR agrochemicals",
     r"fertili[sz]ers?|\burea\b|\bdap\b|\bnbs\b|nutrient[- ]based|\bpotash\b|agrochem|pesticides?|crop protection|nano urea"),
    ("Metals & mining", ["Metals & mining"], ["Iron & Steel Products", "Coal"], "steel \"safeguard duty\" OR \"steel imports\" OR mining policy OR \"critical minerals\" OR aluminium duty OR coal",
     r"\bsteel\b|iron ore|aluminium|\bcopper\b|\bzinc\b|\bmining\b|\bmines\b|\bmmdr\b|critical minerals?|rare earths?|\bcoal\b|safeguard duty|metal(s)? (imports?|exports?|duty)|mineral (auction|block|royalt)|ferro alloys?"),
    ("Oil & gas", ["Oil & gas"], [], "oil gas policy OR \"windfall tax\" OR \"city gas\" OR \"LPG subsidy\" OR \"fuel prices\" OR OALP",
     r"\boil\b|\bgas\b|petrol|diesel|\blpg\b|\bcng\b|\blng\b|\bpng\b|refiner|windfall tax|fuel (prices?|excise|subsid)|\bomcs?\b|\boalp\b|\bapm\b|city gas|\bcgd\b|biofuels?|\bcbg\b|petroleum|crude"),
    ("Textiles", ["Textiles"], [], "textiles PLI OR \"PM MITRA\" OR \"cotton import duty\" OR \"textile exports\" OR RoDTEP",
     r"textiles?|apparel|garments?|\bcotton\b|\byarn\b|pm mitra|\brodtep\b|\brosctl\b|man-?made fibre|\bmmf\b|\bjute\b|\bsilk\b|technical textiles?"),
    ("Media & telecom", ["Media & telecom services"], ["Telecom - Infrastructure"], "telecom AGR OR TRAI OR spectrum auction OR \"tariff hike\" telcos OR broadcasting bill",
     r"telecom|telcos?|\btrai\b|\bagr\b|spectrum|\b[56]g\b|bharatnet|satcom|satellite (internet|broadband)|broadcast|\bott\b|online gaming|media (policy|rules|fdi)|\bdot\b"),
]

# the headline must also name a government / regulator action
POLICY_RX = re.compile(
    r"budget|\boutlay|allocat|cabinet|\bccea\b|\bpli\b|production[- ]linked|\bschemes?\b|\bmission\b|subsid|incentiv|"
    r"polic(y|ies)|(customs|import|export|excise|anti-?dumping|safeguard|countervailing) dut(y|ies)|\bdut(y|ies)\b|"
    r"\bgst\b|\btax(es|ation)?\b|\bcess\b|\broyalt(y|ies)\b|\bfdi\b|"
    r"\bgovt\b|government|\bcentre\b|ministry|minister|niti aayog|\bpmo\b|parliament|\bbill\b|\bact\b|ordinance|"
    r"\brbi\b|\bsebi\b|\btrai\b|\birdai\b|\bnppa\b|\bdgtr\b|\bdgft\b|\bcci\b|\bcerc\b|\bpngrb\b|\bnhai\b|\bfssai\b|\bcdsco\b|"
    r"regulat|\bnorms?\b|\brules?\b|guidelines|notif(y|ies|ied|ication)|mandat|\bban(s|ned)?\b|curbs?|restrict|"
    r"approv|clears?\b|\bnod\b|sanction|tenders?|\bbids?\b|auction|\bmsp\b|\bfrp\b|price (cap|control|ceiling)|"
    r"tariff|trade (deal|pact|agreement)|\bfta\b|\bbta\b|disinvest|privati[sz]|recapitali[sz]|capex|"
    r"₹\s?[\d,.]+\s?(lakh )?(crore|cr)\b|rs\.? ?[\d,.]+\s?(lakh )?(crore|cr)\b", re.I)

# wording that usually helps / hurts companies in the sector (headline only, a rough guess)
POS_RX = re.compile(
    r"approv|clears?\b|\bnod\b|okays?|green ?lights?|sanction|launch(es|ed)?|rolls? out|unveil|announc\w* .{0,40}(scheme|package|mission|outlay|incentive)|"
    r"(hike|raise|increase|boost|double|step up|enhance)[sd]?\b.{0,40}(outlay|allocation|capex|spend|subsid|incentiv|budget|limit|msp|frp)|"
    r"(outlay|allocation|capex|subsid\w*|incentiv\w*|budget)\b.{0,40}(hike|raise|increase|boost|double|higher|record|up \d)|"
    r"\bpli\b|production[- ]linked|incentiv|\bboost\b|\bpush\b|relief|waiv|exempt|eases?\b|relax|extend(s|ed)? .{0,30}(scheme|subsid|incentiv|deadline|exemption)|"
    r"(impos|lev(y|ies)|slap|hike|raise|extend)\w*\b.{0,40}(anti-?dumping|safeguard|import dut|import curbs?|customs duty on imports?)|"
    r"(cut|slash|reduc|lower|remov|scrap)\w*\b.{0,40}(gst|tax|cess|royalt|export dut|excise|compliance)|"
    r"infrastructure status|record (outlay|allocation|capex)|order pipeline|import (ban|curbs?|restrictions?)", re.I)
NEG_RX = re.compile(
    r"(cut|slash|reduc|lower|trim|prun)\w*\b.{0,40}(outlay|allocation|capex|subsid|incentiv|budget|spend|msp)|"
    r"(hike|raise|increase|impos|lev(y|ies)|slap)\w*\b.{0,40}(gst|\btax|cess|royalt|export dut|excise|windfall|penalt|fine)|"
    r"(cut|slash|reduc|lower|remov|scrap|end)\w*\b.{0,40}(import dut|customs dut|anti-?dumping|safeguard|protection)|"
    r"windfall tax|price (cap|control|ceiling|cut)|\bbans?\b.{0,30}(export|sale|production)|export (ban|curbs?|restrictions?)|"
    r"scrap(s|ped)? .{0,30}(scheme|subsid|incentiv|tender)|withdraw|roll(s|ed)? back|defer|delay|stalls?|shelv|"
    r"crackdown|tighten|stricter|curbs?\b|clamp|probe|penalt|show-?cause|"
    r"(us|u\.s\.|trump|eu)\b.{0,40}(tariff|dut(y|ies)|ban|curbs?|sanction)", re.I)

TOPICS_RX = [(n, th, inds, q, re.compile(p, re.I)) for n, th, inds, q, p in TOPICS]


def lean(title):
    p, n = bool(POS_RX.search(title)), bool(NEG_RX.search(title))
    return "up" if p and not n else "down" if n and not p else None


def match_topics(title):
    """Topics a headline belongs to; [] unless it also names a policy action and is not a stock tip."""
    if not POLICY_RX.search(title) or news.NOISE_RX.search(title):
        return []
    return [n for n, _, _, _, rx in TOPICS_RX if rx.search(title)]


def fetch(session):
    """Google News search per topic -> [{t,u,src,ts}] from known publishers only."""
    items = []
    for name, _, _, q, _ in TOPICS_RX:
        url = news.gnews(f"({q}) (budget OR cabinet OR scheme OR policy OR ministry OR duty OR allocation OR govt) India when:7d")
        try:
            r = session.get(url, timeout=25)
            if r.status_code != 200:
                log.warning("%s: HTTP %s", name, r.status_code)
                continue
            got = 0
            for it in news.parse_items(r.content):
                title = news.clean(it["title"])
                pub = news.clean(it.get("src") or (title.rsplit(" - ", 1)[1] if " - " in title else ""))
                src = news.TRUSTED.get(pub.lower())
                if not src or not it["link"]:
                    continue
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0].strip()
                try:
                    ts = parsedate_to_datetime(it["date"]).astimezone(timezone.utc)
                except Exception:
                    continue
                items.append({"t": title, "u": it["link"].strip(), "src": src, "ts": ts.isoformat(timespec="minutes")})
                got += 1
            log.info("%s: %d headlines", name, got)
        except Exception as e:  # noqa: BLE001
            log.warning("%s: %s", name, e)
    return items


def build(raw, prev_items, now):
    """Merge, keep policy headlines per topic, drop repeats of the same story, cap each topic."""
    seen_u, kept = set(), []
    pool = sorted(raw + prev_items, key=lambda x: x["ts"], reverse=True)
    for it in pool:
        if it["u"] in seen_u or now - datetime.fromisoformat(it["ts"]) > timedelta(days=KEEP_DAYS):
            continue
        seen_u.add(it["u"])
        topics = match_topics(it["t"])
        if not topics:
            continue
        kept.append({"t": it["t"], "u": it["u"], "src": it["src"], "ts": it["ts"], "topics": topics, "lean": lean(it["t"])})
    # same story from several outlets: keep one (a top-tier source if there is one), remember the count
    out = []
    for g in news.cluster([dict(k) for k in kept]):
        mem = g["members"]
        lead = sorted(mem, key=lambda m: (m["src"] not in news.TIER1, m["ts"]))[0]
        topics = []
        for m in mem:
            topics += [t for t in m["topics"] if t not in topics]
        row = {"t": lead["t"], "u": lead["u"], "src": lead["src"], "ts": max(m["ts"] for m in mem), "topics": topics}
        if lead["lean"]:
            row["lean"] = lead["lean"]
        n_src = len({m["src"] for m in mem})
        if n_src > 1:
            row["n"] = n_src
        out.append(row)
    out.sort(key=lambda x: x["ts"], reverse=True)
    count, final = {}, []
    for row in out:
        keep = [t for t in row["topics"] if count.get(t, 0) < MAX_PER_TOPIC]
        if not keep:
            continue
        for t in keep:
            count[t] = count.get(t, 0) + 1
        row["topics"] = keep
        final.append(row)
    return final


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
    if not a.force and prev.get("updated") and now - datetime.fromisoformat(prev["updated"]) < timedelta(hours=SKIP_HOURS):
        log.info("policy news is recent; skipping")
        return
    from curl_cffi import requests
    raw = fetch(requests.Session(impersonate="chrome"))
    try:  # headlines the News tab already holds
        with open(news.OUT) as f:
            for o in json.load(f).get("items", []):
                raw.append({"t": o["t"], "u": o["u"], "src": o["src"], "ts": o["ts"]})
    except Exception:
        pass
    if not raw and not prev.get("items"):
        log.error("no headlines fetched; nothing written")
        sys.exit(0)
    items = build(raw, [{k: o[k] for k in ("t", "u", "src", "ts")} for o in prev.get("items", [])], now)
    topics = {n: {"themes": th, "inds": inds} for n, th, inds, _, _ in TOPICS_RX}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT + ".tmp", "w") as f:
        json.dump({"updated": now.isoformat(timespec="minutes"), "keep_days": KEEP_DAYS, "topics": topics, "items": items},
                  f, ensure_ascii=False, separators=(",", ":"))
    os.replace(OUT + ".tmp", OUT)
    log.info("policy: %d headlines kept from %d fetched", len(items), len(raw))


if __name__ == "__main__":
    main()
