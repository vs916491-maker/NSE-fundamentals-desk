"""Extra numbers for banks and lenders (NBFCs, housing finance) on the Stock Screener page.

Read from the same NSE results filings (XBRL) as the rest of the fundamentals:

  banks  (BANKING format)     net interest income, operating profit before provisions, provisions,
                              cost-to-income, Gross / Net NPA %, CET1 and Tier 1 capital, and from the
                              balance sheet: net worth, advances, deposits, total assets
  lenders (NBFC_INDAS format) net interest income, pre-provision profit, impairment (credit cost),
                              cost-to-income, and from the balance sheet: net worth, loans, total assets

Banks give NPA and capital ratios only in the standalone filing (the consolidated one carries zeros),
so ratios are always taken from standalone. The balance sheet is filed with half-year and full-year
results only, so book value can be up to a quarter old. Insurers, brokers and asset managers also
file in a "financial" format but have none of these fields: they get kind "" and nothing extra.

Parsed filings are kept in cache/fin/<SYM>.json under "fc|<nature>|<quarter end>".
"""
import logging
import os
import time
from datetime import date

import xbrl

log = logging.getLogger("finco")
FC_VERSION = 1


def parse(doc: str, qe: date):
    """{"k": "bank" | "nbfc" | "", "p": {...quarter, Rs crore}, "r": {...ratios, %}, "bs": {...Rs crore} or None}"""
    ctxs = xbrl._contexts(doc)
    facts = xbrl._facts(doc)
    qctx = ictx = None
    for cid, c in ctxs.items():
        if c["dims"]:
            continue
        if c["start"] and c["end"] == qe and 80 <= (c["end"] - c["start"]).days <= 100:
            qctx = cid
        if c["instant"] == qe:
            ictx = cid
    out = {"_fv": FC_VERSION, "k": ""}
    if qctx is None:
        return out

    def v(name, ctx=qctx):
        x = xbrl._num(facts.get(name, {}).get(ctx)) if ctx else None
        return None if x is None else round(x / 1e7, 2)

    def raw(name):
        return xbrl._num(facts.get(name, {}).get(qctx))

    def add(*xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs), 2) if xs else None

    def cti(opex, income):
        return round(opex / income * 100, 1) if opex is not None and income and income > 0 else None

    if "InterestExpended" in facts:                      # banking format
        ie, ix, oi, opex = v("InterestEarned"), v("InterestExpended"), v("OtherIncome"), v("OperatingExpenses")
        if ie is None or ix is None:
            return out
        nii = round(ie - ix, 2)
        out["k"] = "bank"
        out["p"] = {"nii": nii, "ppop": v("OperatingProfitBeforeProvisionAndContingencies"),
                    "prov": v("ProvisionsOtherThanTaxAndContingencies"), "cti": cti(opex, nii + (oi or 0))}
        g, nn, c1, a1 = raw("PercentageOfGrossNpa"), raw("PercentageOfNpa"), raw("CET1Ratio"), raw("AdditionalTier1Ratio")
        if g or c1:                                       # zeros = consolidated filing, ratios not given
            # filed as fractions (0.0111 = 1.11%); a few filers type the percentage itself
            k = 1 if (c1 and c1 > 1) or (not c1 and g and g > 0.3) else 100
            pc = lambda x: None if x is None else round(x * k, 2)
            out["r"] = {"gnpa": pc(g), "nnpa": pc(nn), "cet1": pc(c1) if c1 else None,
                        "t1": pc(c1 + (a1 or 0)) if c1 else None,
                        # the bank's own cost-to-income (consolidated mixes in insurance and other subsidiaries)
                        "cti": out["p"]["cti"]}
        if ictx and v("Assets", ictx):
            out["bs"] = {"e": qe.isoformat(), "nw": add(v("Capital", ictx), v("ReservesAndSurplus", ictx)),
                         "adv": v("Advances", ictx), "dep": v("Deposits", ictx), "ta": v("Assets", ictx)}
        return out

    ie, fc, rev = v("InterestEarned"), v("FinanceCosts"), v("RevenueFromOperations")
    if ie is None or fc is None or not rev or ie < 0.5 * rev:   # not mainly a lender (broker, AMC, insurer, holding co.)
        return out
    imp, exp, inc = v("ImpairmentOnFinancialInstruments") or 0.0, v("Expenses"), v("Income") or rev
    pbt = v("ProfitBeforeExceptionalItemsAndTax")
    if pbt is None:
        pbt = v("ProfitBeforeTax")
    out["k"] = "nbfc"
    out["p"] = {"nii": round(ie - fc, 2), "ppop": None if pbt is None else round(pbt + imp, 2), "prov": imp,
                "cti": cti(None if exp is None else exp - fc - imp, inc - fc)}
    if ictx and v("Assets", ictx):
        nw = v("EquityAttributableToOwnersOfParent", ictx) or v("Equity", ictx) \
            or add(v("EquityShareCapital", ictx), v("OtherEquity", ictx))
        out["bs"] = {"e": qe.isoformat(), "nw": nw, "adv": v("Loans", ictx), "ta": v("Assets", ictx),
                     "bor": add(v("DebtSecurities", ictx), v("Borrowings", ictx), v("Deposits", ictx), v("SubordinatedLiabilities", ictx))}
    return out


def _prev_qe(qe):
    from fundamentals import _prev_qe as f
    return f(qe)


def _year_ago(qe):
    from fundamentals import _year_ago as f
    return f(qe)


def build(fund, sym, rec):
    """rec["fc"] for one bank / lender record. Raises on a download error (retried next run)."""
    qe = date.fromisoformat(rec["qe"])
    nature = rec.get("nat") or "Standalone"
    hist = {}
    for h in sorted(fund.c.fin_listing(sym, strict=True), key=lambda x: x.get("creation_Date") or ""):
        q = fund.parse_date(h.get("qe_Date") or "")
        if q and h.get("xbrl"):
            hist[(h.get("consolidated") or "Standalone", q)] = h["xbrl"]
    cache_path = os.path.join(fund.c.cache_dir, "fin", f"{sym}.json")
    cache = fund.jload(cache_path, {})

    def get(nat, q):
        key = f"fc|{nat}|{q.isoformat()}"
        if (cache.get(key) or {}).get("_fv") == FC_VERSION:
            return cache[key]
        url = hist.get((nat, q))
        if not url:
            return None
        cache[key] = parse(fund.c.n.get(url, raw=True).decode(errors="ignore"), q)
        return cache[key]

    try:
        cur = get(nature, qe)
        fc = {"v": FC_VERSION, "qe": rec["qe"], "k": (cur or {}).get("k", "")}
        if not fc["k"]:
            return fc
        pq, py = _prev_qe(qe), _year_ago(qe)
        prev, yago = get(nature, pq), get(nature, py)
        fc["q"] = cur["p"]
        if prev and prev.get("p"):
            fc["pq"] = prev["p"]
        if yago and yago.get("p"):
            fc["py"] = yago["p"]
        # balance sheet: this quarter's, else last quarter's (it is filed only with half-year and full-year results)
        bs = cur.get("bs") or (prev or {}).get("bs")
        if bs:
            fc["bs"] = bs
            old = get(nature, _year_ago(date.fromisoformat(bs["e"])))
            if old and old.get("bs"):
                fc["bs_py"] = old["bs"]
        if fc["k"] == "bank":                         # NPA and capital ratios: standalone filings only
            for key, q in (("r", qe), ("rpq", pq), ("rpy", py)):
                d = cur if (key == "r" and cur.get("r")) else get("Standalone", q)
                if d and d.get("r"):
                    fc[key] = d["r"]
        return fc
    finally:
        fund.jsave(cache_path, cache)


def fill(fund, minutes=10.0):
    """Add / refresh "fc" on bank and lender records (largest by turnover first)."""
    end = time.time() + minutes * 60
    todo = [s for s, r in fund.rows.items() if r.get("finco") and r.get("qe")
            and not ((r.get("fc") or {}).get("v") == FC_VERSION and r["fc"].get("qe") == r["qe"])]
    todo.sort(key=lambda s: -(fund.c.turnover.get(s) or 0))
    done = with_data = 0
    errors = []
    for sym in todo:
        if time.time() > end:
            break
        try:
            fund.rows[sym]["fc"] = build(fund, sym, fund.rows[sym])
            with_data += bool(fund.rows[sym]["fc"].get("k"))
        except Exception as e:  # noqa: BLE001
            log.warning("finco %s: %s", sym, e)
            errors.append(f"{sym}: {str(e)[:100]}")
            if len(errors) >= 10:
                break
        done += 1
    if todo:
        print(f"::notice title=Banks and lenders::{done} checked, {with_data} with bank / lender numbers, "
              f"{len(todo) - done} left for later runs" + (f"; errors e.g. {' | '.join(errors[:3])}" if errors else ""))
    return done
