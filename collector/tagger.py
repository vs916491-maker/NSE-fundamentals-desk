"""Tag NSE announcements and pull the order value out of the text.

Tags: Order, Penalty, Buyback, Results, Rating, RedFlag, Management, Other.
NSE gives each filing a category in `desc`; that is used first. For generic
categories ("General Updates", "Updates", "Press Release") the text is checked.
"""
import re

TAGS = ["Results", "Order", "Penalty", "Buyback", "Rating", "RedFlag", "Management", "Other"]

# Exact / prefix NSE categories -> tag
SUBJECT_MAP = [
    (r"^bagging/receiving of orders", "Order"),
    (r"^awarding of order", "Order"),
    (r"^action\(s\) (taken|initiated)", "Penalty"),
    (r"^pendency of litigation", "Penalty"),
    (r"^(buy ?back|buyback)", "Buyback"),
    (r"^credit rating", "Rating"),
    (r"^(initiation of forensic audit|corporate insolvency resolution|default|disclosure of default|"
     r"suspension of trading|fraud|closure of operations)", "RedFlag"),
    (r"^change in auditors", "Management"),
    (r"^(resignation|cessation|change in management|change in director|appointment|retirement|demise)", "Management"),
    (r"^(integrated filing- financial|financial result|clarification - financial results)", "Results"),
]
_SUBJ = [(re.compile(p, re.I), t) for p, t in SUBJECT_MAP]

GENERIC = re.compile(r"^(general updates|updates|press release|press release \(revised\)|others|"
                     r"outcome of board meeting|disclosure of material issue)", re.I)

TEXT_RULES = [
    ("Buyback", [r"\bbuy[\s-]?back"]),
    ("Penalty", [r"\bpenalt", r"show[\s-]?cause", r"demand order", r"\bdemand of\b", r"\blevied\b",
                 r"adjudicat", r"order[s]? (passed|received) under section", r"\bsebi order"]),
    ("Order", [r"\b(bag|bagged|bagging|bags|receipt of|received|receives|secured|secures|securing|wins?|won|awarded)\b"
               r".{0,60}\b(orders?|contracts?|work orders?|LoA|LOI|letter of (award|intent|acceptance))\b",
               r"\b(orders?|contracts?)\b.{0,40}\b(received|bagged|secured|awarded|won)\b",
               r"\b(letter of (award|intent|acceptance)|LoA|LOI)\b"]),
    ("Rating", [r"credit rating", r"\brating\b.{0,40}\b(upgrade|downgrade|reaffirm|revised|assigned)"]),
]
_TEXT = [(t, [re.compile(p, re.I | re.S) for p in ps]) for t, ps in TEXT_RULES]

_NOISE = re.compile(r"(newspaper|publication|trading window|analyst|investor (meet|call|presentation)|"
                    r"earnings call|transcript|audio recording|recording of)", re.I)
_RESULTS_TEXT = re.compile(r"(financial results?|results? for the (quarter|period|half))", re.I)
_AUDITOR = re.compile(r"\bauditor", re.I)
_RESIGN = re.compile(r"resign", re.I)


def tag(subject: str, text: str = "") -> str:
    subject = (subject or "").strip()
    text = text or ""
    if _NOISE.search(subject):
        return "Other"
    for rx, t in _SUBJ:
        if rx.search(subject):
            if t == "Management" and _RESIGN.search(subject + " " + text[:400]) and _AUDITOR.search(subject + " " + text[:400]):
                return "RedFlag"  # auditor resignation
            if t == "Management" and re.match(r"change in auditors", subject, re.I) and _RESIGN.search(text[:400]):
                return "RedFlag"
            return t
    if GENERIC.search(subject):
        head = text[:700]
        if _NOISE.search(head):
            return "Other"
        if re.match(r"outcome of board meeting", subject, re.I):
            if _RESULTS_TEXT.search(head):
                return "Results"
            if re.search(r"\bbuy[\s-]?back", head, re.I):
                return "Buyback"
            return "Other"
        for t, pats in _TEXT:
            if any(p.search(head) for p in pats):
                return t
    return "Other"


def rating_direction(text: str):
    t = (text or "").lower()
    if re.search(r"downgrad|negative|withdrawn.*default|\bdefault", t):
        return "down"
    if re.search(r"upgrad|positive", t):
        return "up"
    return None


_AMT = re.compile(
    r"(?P<cur>₹|rs\.?|inr|usd|us\$|\$|eur|€)\s*"
    r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<unit>lakh crores?|crores?|cr\b|cr\.|lakhs?|lacs?|millions?|mn\b|billions?|bn\b)?",
    re.I,
)
_AMT_SUFFIX = re.compile(r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>crores?|cr\b|lakhs?)", re.I)


def _to_crore(num, cur, unit):
    unit = (unit or "").lower()
    if cur in ("usd", "us$", "$", "eur", "€"):
        return None
    if unit.startswith("lakh crore"):
        return num * 100000
    if unit.startswith(("crore", "cr")):
        return num
    if unit.startswith(("lakh", "lac")):
        return num / 100
    if unit.startswith(("million", "mn")):
        return num / 10
    if unit.startswith(("billion", "bn")):
        return num * 100
    if not unit and num >= 1e5:
        return num / 1e7
    return None


def amount(text: str):
    """Largest INR amount in the text as (crore or None, raw snippet or None)."""
    if not text:
        return None, None
    best, raw = None, None
    for m in _AMT.finditer(text):
        cur = m.group("cur").lower().rstrip(".")
        num = float(m.group("num").replace(",", ""))
        cr = _to_crore(num, cur, m.group("unit"))
        snip = m.group(0).strip()
        if cr is None:
            if raw is None and m.group("unit"):
                raw = snip
            continue
        if best is None or cr > best:
            best, raw = cr, snip
    if best is None:
        for m in _AMT_SUFFIX.finditer(text):
            cr = _to_crore(float(m.group("num").replace(",", "")), "inr", m.group("unit"))
            if cr and (best is None or cr > best):
                best, raw = cr, m.group(0).strip()
    if best is not None and best > 500000:
        return None, raw
    return (round(best, 2) if best is not None else None), raw


INSTITUTION = re.compile(
    r"(mutual fund|\bmf\b|insurance|assurance|life\b|pension|provident|\bfund\b|funds\b|asset management|"
    r"\bamc\b|investment trust|sicav|\bplc\b|\bllc\b|\bl\.?p\.?\b|capital group|vanguard|blackrock|"
    r"government of|monetary authority|norges|abu dhabi|kuwait|qatar|\bbank\b|"
    r"société générale|societe generale|morgan stanley asia|goldman sachs \(singapore|bnp paribas|citigroup global)",
    re.I)
PROP_DESK = re.compile(r"(securities research|hrti|qe securities|alphagrep|microcurves|irage|graviton|"
                       r"nk securities|junomoneta|silverleaf|plutus wealth|j4s financial|tower research|"
                       r"jump trading|edelweiss custodial|share broking)", re.I)


def is_institution(name: str) -> bool:
    return bool(INSTITUTION.search(name or "")) and not PROP_DESK.search(name or "")
