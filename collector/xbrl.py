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


REVENUE = ["RevenueFromOperations", "InterestEarned", "TotalRevenueFromOperations", "NetPremiumIncome", "Income"]
PAT = ["ProfitOrLossAttributableToOwnersOfParent", "ProfitLossForPeriod", "ProfitLossForThePeriod",
       "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
       "ProfitLossFromOrdinaryActivitiesAfterTax", "ProfitLossForPeriodFromContinuingOperations",
       "ProfitLossAfterTaxAndExtraordinaryItems", "ProfitLossAfterTaxBeforeExtraordinaryItems"]
PBT = ["ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax", "ProfitBeforeExceptionalItemsAndTax", "ProfitLossBeforeTax"]
EPS = ["BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
       "BasicEarningsPerShareAfterExtraordinaryItems", "BasicEarningsLossPerShareFromContinuingOperations",
       "BasicEarningsPerShareBeforeExtraordinaryItems",
       "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized"]


FIN_VERSION = 3  # results parses (separate from shareholding so those caches stay valid)
OTHER_INC = ["OtherIncome"]
TOTAL_EXP = ["Expenses", "TotalExpenses"]
FIN_COST = ["FinanceCosts", "FinanceCost"]
DEPR = ["DepreciationDepletionAndAmortisationExpense", "DepreciationAndAmortisationExpense"]
EXCEPTIONAL = ["ExceptionalItemsBeforeTax", "ExceptionalItems"]
TAX = ["TaxExpense", "TotalTaxExpense", "TaxExpenseIncome"]
# element names that only appear in bank / lender / insurer formats (operating margin is not meaningful there)
FINANCIAL_MARKERS = ["InterestEarned", "InterestExpended", "FeesAndCommissionIncome", "NetGainOnFairValueChanges",
                     "NetPremiumEarned", "PremiumsEarnedNet", "InterestIncome", "NetPremiumIncome", "GrossPremiumIncome"]


def parse_results(doc: str, qe: date):
    """Quarter metrics in Rs crore (EPS in Rs) for the 3-month period ending qe, or None.

    NSE's integrated-filing XBRL carries only this quarter and the year to date
    (no comparison columns), so "periods" has "q" and, from the second quarter
    on, "ytd"; comparisons come from the earlier filings."""
    ctxs = _contexts(doc)
    facts = _facts(doc)
    plain = {cid: c for cid, c in ctxs.items() if not c["dims"] and c["start"] and c["end"]}

    def find(end, lo, hi):
        best = None
        for cid, c in plain.items():
            days = (c["end"] - c["start"]).days
            if end is not None and c["end"] != end:
                continue
            if lo <= days <= hi and (best is None or days > (plain[best]["end"] - plain[best]["start"]).days):
                best = cid
        return best

    qctx = find(qe, 80, 100)
    if qctx is None:
        return None

    def pick(names, ctx, scale=1e7):
        # first non-zero candidate: some filers put 0 in e.g. "attributable to owners"
        zero = None
        for n in names:
            v = _num(facts.get(n, {}).get(ctx))
            if v is None:
                continue
            if v != 0:
                return round(v / scale, 2)
            zero = 0.0
        return zero

    financial = any(m in facts for m in FINANCIAL_MARKERS)

    def metrics(ctx):
        if ctx is None:
            return None
        m = {"rev": pick(REVENUE, ctx), "pat": pick(PAT, ctx), "pbt": pick(PBT, ctx), "eps": pick(EPS, ctx, 1),
             "oi": pick(OTHER_INC, ctx), "exp": pick(TOTAL_EXP, ctx), "fin": pick(FIN_COST, ctx),
             "dep": pick(DEPR, ctx), "exc": pick(EXCEPTIONAL, ctx), "tax": pick(TAX, ctx)}
        c = plain[ctx]
        m["start"], m["end"] = c["start"].isoformat(), c["end"].isoformat()
        # operating profit (EBITDA, before other income): revenue - (expenses - finance costs - depreciation)
        if not financial and m["rev"] is not None and m["exp"] is not None:
            m["op"] = round(m["rev"] - (m["exp"] - (m["fin"] or 0) - (m["dep"] or 0)), 2)
        return m

    ytd = find(qe, 101, 380)
    periods = {"q": metrics(qctx), "ytd": metrics(ytd)}
    cur = periods["q"]
    nature = (facts.get("NatureOfReportStandaloneConsolidated", {}).get(qctx) or "").strip()
    return {
        "_v": FIN_VERSION,
        "rev": cur["rev"], "pat": cur["pat"], "pbt": cur["pbt"], "eps": cur["eps"],
        "nature": nature or None,
        "financial": financial,
        "periods": {k: v for k, v in periods.items() if v},
        "fy_end": next((v.strip()[:10] for v in facts.get("DateOfEndOfFinancialYear", {}).values() if v.strip()), None),
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
