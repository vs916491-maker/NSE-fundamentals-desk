"""Tag NSE announcements by category and pull the order value out of the text."""
import re

# Order matters: first match wins.
RULES = [
    ("Buyback", [r"\bbuy[\s-]?back"]),
    ("Penalty", [r"\bpenalt", r"\bfine[sd]?\b", r"show[\s-]?cause", r"action\(s\) (taken|initiated)",
                 r"orders? passed by", r"demand order", r"\bdemand of\b", r"\bsebi order", r"\blevied\b",
                 r"adjudicat"]),
    ("Order", [r"bagging/receiving of orders", r"\b(bag|bagged|bagging|receipt of|received|receives|secured|securing|wins?|won|bags)\b.{0,60}\b(orders?|contracts?|work orders?|LoA|LOI|letter of (award|intent|acceptance))\b",
               r"\b(orders?|contracts?)\b.{0,40}\b(received|bagged|secured|awarded|won)\b",
               r"\b(letter of (award|intent|acceptance)|LoA|LOI|work order|purchase order)\b"]),
    ("Results", [r"financial results?", r"\bresults? for the (quarter|period|half)", r"financial result updates"]),
    ("Rating", [r"credit rating", r"\brating\b.{0,40}\b(upgrade|downgrade|reaffirm|revised|assigned)"]),
    ("Resignation", [r"resignation", r"\bresigns?\b"]),
]
_COMPILED = [(tag, [re.compile(p, re.I | re.S) for p in pats]) for tag, pats in RULES]

# Subjects that look like matches but are not the event itself.
_NOISE = re.compile(r"(newspaper|publication|intimation of (board|record)|trading window|"
                    r"analyst|investor (meet|call|presentation)|earnings call|transcript|audio recording)", re.I)


def tag(subject: str, text: str = "") -> str:
    subject = subject or ""
    text = text or ""
    for t, pats in _COMPILED:
        if t in ("Results",) and _NOISE.search(subject):
            continue
        if any(p.search(subject) for p in pats):
            if t == "Order" and _NOISE.search(subject):
                continue
            return t
    # Subject is often generic ("General Updates"); look at the first part of the body text.
    head = text[:600]
    if re.search(r"outcome of board meeting", subject, re.I) and re.search(r"financial results?", head, re.I):
        return "Results"
    for t, pats in _COMPILED:
        if t in ("Results", "Resignation"):
            continue  # too noisy in body text
        if any(p.search(head) for p in pats) and not _NOISE.search(subject):
            return t
    return "Other"


def is_auditor_resignation(subject: str, text: str = "") -> bool:
    s = f"{subject} {text[:400]}"
    return bool(re.search(r"resign", s, re.I) and re.search(r"\bauditor", s, re.I))


_AMT = re.compile(
    r"(?P<cur>₹|rs\.?|inr|usd|us\$|\$|eur|€)\s*"
    r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<unit>lakh crores?|lakh crore|crores?|cr\b|cr\.|lakhs?|lacs?|millions?|mn\b|billions?|bn\b)?",
    re.I,
)
_AMT_SUFFIX = re.compile(  # "1,234 crore" without a currency prefix, near "order"/"value"
    r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>crores?|cr\b|lakhs?)", re.I)


def _to_crore(num: float, cur: str, unit: str):
    unit = (unit or "").lower()
    if cur in ("usd", "us$", "$", "eur", "€"):
        return None  # foreign currency: show raw text only
    if "lakh crore" in unit:
        return num * 100000
    if unit.startswith(("crore", "cr")):
        return num
    if unit.startswith(("lakh", "lac")):
        return num / 100
    if unit.startswith(("million", "mn")):
        return num / 10
    if unit.startswith(("billion", "bn")):
        return num * 100
    if not unit and num >= 1e5:  # plain rupees
        return num / 1e7
    return None


def order_value(text: str):
    """Return (value_in_crore or None, raw_snippet or None). Takes the largest INR amount found."""
    if not text:
        return None, None
    best, raw = None, None
    for m in _AMT.finditer(text):
        cur = m.group("cur").lower().rstrip(".")
        num = float(m.group("num").replace(",", ""))
        unit = m.group("unit")
        cr = _to_crore(num, cur, unit)
        snippet = m.group(0).strip()
        if cr is None:
            if raw is None and unit:
                raw = snippet
            continue
        if best is None or cr > best:
            best, raw = cr, snippet
    if best is None:
        for m in _AMT_SUFFIX.finditer(text):
            num = float(m.group("num").replace(",", ""))
            cr = _to_crore(num, "inr", m.group("unit"))
            if cr and (best is None or cr > best):
                best, raw = cr, m.group(0).strip()
    if best is not None and best > 5_00_000:  # > ₹5 lakh crore is almost surely a parse error
        return None, raw
    return (round(best, 2) if best is not None else None), raw
