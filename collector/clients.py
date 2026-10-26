"""Classify bulk/block deal clients as FII, DII, Fund (AIF/PMS/other fund) or None.

NSE gives only the client name, so this is a name-based guess. Order of checks:
  1. manual overrides in clients.json (edit that file to fix a misclassification)
  2. known foreign institutions               -> FII
  3. HFT / prop / broker desks                 -> None (excluded)
  4. domestic MF / insurer / pension / AIF     -> DII  (unless the name looks foreign)
  5. foreign legal-form or country markers     -> FII
  6. other funds, AIFs, PMS, asset managers    -> Fund
  7. everyone else (individuals, companies)    -> None
"""
import json, os, re

_HERE = os.path.dirname(__file__)

FII_NAMES = re.compile(
    r"(government of singapore|monetary authority|investment authority|norges bank|kuwait|qatar|"
    r"goldman sachs|morgan stanley|societe generale|soci[eé]t[eé] g[eé]n[eé]rale|bnp paribas|citigroup|"
    r"j\.?\s?p\.?\s?morgan|merrill lynch|bofa securities|\bubs\b|nomura|barclays|credit suisse|deutsche bank|"
    r"vanguard|blackrock|ishares|fidelity|t\.? ?rowe price|euro pacific|new world fund|smallcap world fund|"
    r"capital group|ghisallo|integrated core strategies|susquehanna|general atlantic|warburg|kkr|carlyle|"
    r"temasek|\bgic\b|pabrai|polar capital|pacific assets trust|aberdeen|abrdn|schroder|invesco (asia|funds|india equity)|"
    r"wellington|state street|nordea|amundi|eastspring|matthews|kotak funds|hsbc global|baron|wasatch|"
    r"\bodi\b)", re.I)

PROP = re.compile(
    r"(securities|broking|brokers|stock|shares|share and|trading|tradetech|trade solutions|capital market|"
    r"commodities|quant|research|wealth management|finsol|finvest|fintech|intermediaries|"
    r"hrti|microcurves|junomoneta|alphagrep|irage|graviton|plutus|elixir|grt strategic|blitzquant|"
    r"mathisys|musigma|silverleaf|j4s|imc india|clt research|bullpulse|patronus|vistaar|neo apex|"
    r"jump trading|tower research|dipan mehta|yuga|puma|prognosis|setu|goldmine|acme capital|mansukh|"
    r"marwadi|jainam|arihant capital|vt capital|d3 stock|l7 hitech|vinsul|catamaran|two roads)", re.I)

DII = re.compile(
    r"(mutual fund|\bmf\b|life insurance|insurance co|general insurance|assurance|pension system|\bnps\b|"
    r"provident fund|employees.? provident|\baif\b|alternative investment|life insurance corporation|"
    r"\btrustee\b.*\ba/?c\b|\bamc\b|asset management (co|company|limited|ltd)|\bbank (limited|ltd)\b)", re.I)

FOREIGN = re.compile(
    r"(\bpcc\b|\bspc\b|\bspv (limited|ltd)|mother fund|fund (limited|ltd)\.?$|global opportunities|\baps$|"
    r"mauritius|singapore|cayman|luxembourg|ireland|netherlands|delaware|\(de\)|\bdubai\b|hong kong|"
    r"\bpte\b|\bplc\b|\bllc\b|\bpty\b|\bb\.?\s?v\.?$|\bb v\b|\bgmbh\b|\bvcc\b|\bsicav\b|\bicav\b|\bucits\b|"
    r"\binc\.?$|\bl\.?p\.?$|\blp\b|\bs\.?a\.?$|\bse$|\bag$|master fund|asian|\basia\b|apac|"
    r"emerging markets|international .*fund|global fund|funds? plc)", re.I)

FUND = re.compile(
    r"(\bfunds?\b|\bscheme\b|investment managers|asset management|asset managers|capital partners|"
    r"opportunities|\betf\b|portfolio|\bpms\b|\btrust\b.*\bfund)", re.I)


# Indian AMC scheme names that don't say "mutual fund", e.g. "FRANKLIN INDIA FLEXI CAP FUND"
AMC_SCHEME = re.compile(
    r"^(the )?(sbi|hdfc|icici prudential|nippon india|kotak mahindra|axis|uti|dsp|tata|mirae asset|"
    r"aditya birla sun life|invesco india|bandhan|edelweiss|quant|parag parikh|ppfas|canara robeco|sundaram|"
    r"whiteoak|baroda bnp paribas|lic|union|360 one|helios|groww|jm financial|iti|taurus|mahindra manulife|"
    r"hsbc|navi|samco|old bridge|franklin india|motilal oswal|bank of india|pgim india|nj|trust|zerodha|"
    r"bajaj finserv|quantum|shriram|unifi)\b.*\b(funds?|scheme)\b", re.I)


def _overrides():
    try:
        with open(os.path.join(_HERE, "clients.json")) as f:
            raw = json.load(f)
        return [(t, n.upper()) for t, names in raw.items() if not t.startswith("_") for n in names]
    except Exception:
        return []


_OV = _overrides()


def classify(name: str):
    n = (name or "").strip()
    if not n:
        return None
    up = n.upper()
    for t, sub in _OV:
        if sub in up:
            return None if t == "Exclude" else t
    if AMC_SCHEME.search(n) and not FOREIGN.search(n):
        return "DII"
    if FII_NAMES.search(n):
        return "FII"
    if PROP.search(n) and not DII.search(n):
        return None
    if DII.search(n) and not FOREIGN.search(n):
        return "DII"
    if FOREIGN.search(n):
        # foreign holding companies of promoters / PE are still foreign money; keep as FII
        return "FII"
    if FUND.search(n):
        return "Fund"
    return None
