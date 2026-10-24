"""Parse NSE Integrated Filing (financial results) and Shareholding Pattern XBRL files."""
import re
from datetime import date

VERSION = 2  # bump to invalidate cached parses

_CTX = re.compile(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', re.S)
_FACT = re.compile(r'<([\w-]+):(\w+)\b([^>]*?)contextRef="([^"]+)"[^>]*>([^<]*)<', re.S)


def _d(s):
    try:
        return date.fromisoformat(s.strip()[:10])
    except Exception:
        return None


def _contexts(doc):
    out = {}
    for cid, body in _CTX.findall(doc):
        sd = re.search(r"<xbrli:startDate>([^<]+)", body)
        ed = re.search(r"<xbrli:endDate>([^<]+)", body)
        inst = re.search(r"<xbrli:instant>([^<]+)", body)
        dims = "explicitMember" in body or "typedMember" in body
        out[cid] = {"start": _d(sd.group(1)) if sd else None,
                    "end": _d(ed.group(1)) if ed else None,
                    "instant": _d(inst.group(1)) if inst else None,
                    "dims": dims}
    return out


def _facts(doc):
    facts = {}
    for _ns, name, _attrs, ctx, val in _FACT.findall(doc):
        facts.setdefault(name, {})[ctx] = val.strip()
    return facts


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


REVENUE = ["RevenueFromOperations", "InterestEarned", "TotalRevenueFromOperations", "Income"]
PAT = ["ProfitOrLossAttributableToOwnersOfParent", "ProfitLossForPeriod", "ProfitLossForThePeriod",
       "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
       "ProfitLossFromOrdinaryActivitiesAfterTax", "ProfitLossForPeriodFromContinuingOperations"]
PBT = ["ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax", "ProfitBeforeExceptionalItemsAndTax"]
EPS = ["BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
       "BasicEarningsPerShareAfterExtraordinaryItems", "BasicEarningsLossPerShareFromContinuingOperations",
       "BasicEarningsPerShareBeforeExtraordinaryItems"]


def parse_results(doc: str, qe: date):
    """Return quarter metrics in ₹ crore (EPS in ₹) for the 3-month period ending qe, or None."""
    ctxs = _contexts(doc)
    facts = _facts(doc)
    qctx = None
    for cid, c in ctxs.items():
        if c["dims"] or not c["start"] or not c["end"]:
            continue
        days = (c["end"] - c["start"]).days
        if c["end"] == qe and 80 <= days <= 100:
            qctx = cid
            break
    if qctx is None:
        return None

    def pick(names, scale=1e7):
        # first non-zero candidate: some filers put 0 in e.g. "attributable to owners"
        zero = None
        for n in names:
            v = _num(facts.get(n, {}).get(qctx))
            if v is None:
                continue
            if v != 0:
                return round(v / scale, 2)
            zero = 0.0
        return zero

    nature = (facts.get("NatureOfReportStandaloneConsolidated", {}).get(qctx) or "").strip()
    return {
        "_v": VERSION,
        "rev": pick(REVENUE),
        "pat": pick(PAT),
        "pbt": pick(PBT),
        "eps": pick(EPS, scale=1),
        "nature": nature or None,
    }


SHP_GROUPS = {
    "promoter": "ShareholdingOfPromoterAndPromoterGroup_ContextI",
    "fii": "InstitutionsForeign_ContextI",
    "dii": "InstitutionsDomestic_ContextI",
    "public": "PublicShareholding_ContextI",
}


def parse_shp(doc: str):
    """Return % holdings (0-100) by group plus total shares."""
    facts = _facts(doc)
    pct = facts.get("ShareholdingAsAPercentageOfTotalNumberOfShares", {})
    out = {}
    for k, ctx in SHP_GROUPS.items():
        v = _num(pct.get(ctx))
        out[k] = round(v * 100, 2) if v is not None else None
    mf_keys = [k for k in pct if re.match(r"MutualFund\w*_ContextI$", k)]
    vals = [_num(pct[k]) for k in mf_keys]
    vals = [v for v in vals if v is not None]
    out["mf"] = round(max(vals) * 100, 2) if vals else None
    tot = _num(facts.get("NumberOfShares", {}).get("ShareholdingPattern_ContextI")) \
        or _num(facts.get("NumberOfFullyPaidUpEquityShares", {}).get("ShareholdingPattern_ContextI"))
    out["shares"] = tot
    out["_v"] = VERSION
    return out
