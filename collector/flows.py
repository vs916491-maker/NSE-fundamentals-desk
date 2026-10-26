"""FII/DII daily flows and institutional bulk/block deal history.

Writes:
  site/data/flows.json        {date: {cash, fo, poi}}   - FII/DII activity per trading day
  site/data/inst_deals.json   institutional bulk/block deals for the last ~95 days
"""
import csv, io, logging, os
from datetime import date, datetime, timedelta

import clients

log = logging.getLogger("flows")
DEAL_DAYS = 95
FLOW_KEEP = 180
HIST = "/api/historicalOR/bulk-block-short-deals"
DEALS_REFERER = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"


def _f(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _d(s):
    s = (s or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:11].title() if "%b" in fmt else s[:10], fmt).date()
        except ValueError:
            pass
    return None


# ---------------- bulk / block deal history ----------------
def deal_history(n, d_from: date, d_to: date):
    """All bulk + block deals between two dates (inclusive) from NSE's CSV export, 30-day chunks."""
    rows = []
    old_ref = n.s.headers.get("Referer")
    n.s.headers["Referer"] = DEALS_REFERER
    try:
        for kind, opt in (("bulk", "bulk_deals"), ("block", "block_deals")):
            a = d_from
            while a <= d_to:
                b = min(a + timedelta(days=29), d_to)
                try:
                    raw = n.get(HIST, {"optionType": opt, "from": a.strftime("%d-%m-%Y"),
                                       "to": b.strftime("%d-%m-%Y"), "csv": "true"}, raw=True)
                    text = raw.decode("utf-8-sig", errors="ignore")
                    if text.lstrip().startswith("<"):
                        raise RuntimeError("got HTML instead of CSV")
                    for r in csv.DictReader(io.StringIO(text)):
                        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
                        dd = _d(r.get("Date", ""))
                        qty = _f(r.get("Quantity Traded"))
                        px = _f(r.get("Trade Price / Wght. Avg. Price"))
                        if not dd or qty is None or px is None:
                            continue
                        rows.append({"date": dd.isoformat(), "kind": kind, "sym": r.get("Symbol"),
                                     "name": r.get("Security Name"), "client": r.get("Client Name", ""),
                                     "side": r.get("Buy / Sell", r.get("Buy/Sell", "")).upper(),
                                     "qty": qty, "price": px, "value_cr": round(qty * px / 1e7, 2)})
                except Exception as e:
                    log.warning("deal history %s %s..%s: %s", kind, a, b, e)
                a = b + timedelta(days=1)
    finally:
        if old_ref:
            n.s.headers["Referer"] = old_ref
    for r in rows:
        t = clients.classify(r["client"])
        r["itype"] = t
        r["inst"] = t is not None
    log.info("deal history %s..%s: %d rows", d_from, d_to, len(rows))
    return rows


def write_inst_deals(path, rows, d_to: date, shares_fn, mcap_fn, jsave):
    """Keep only institutional deals; add shares / market cap for the stocks involved."""
    inst = [r for r in rows if r.get("inst")]
    syms = sorted({r["sym"] for r in inst})
    shares, mcap, names = {}, {}, {}
    for r in inst:
        names[r["sym"]] = r["name"]
    for s in syms:
        try:
            sh = shares_fn(s)
            if sh:
                shares[s] = sh
            mc = mcap_fn(s)
            if mc:
                mcap[s] = mc
        except Exception as e:
            log.warning("shares %s: %s", s, e)
    compact = [[r["date"], r["kind"], r["sym"], r["client"], r["side"], r["qty"], r["price"], r["value_cr"], r["itype"]]
               for r in sorted(inst, key=lambda r: (r["date"], r["sym"]))]
    jsave(path, {"to": d_to.isoformat(), "from": (d_to - timedelta(days=DEAL_DAYS)).isoformat(),
                 "cols": ["date", "kind", "sym", "client", "side", "qty", "price", "value_cr", "type"],
                 "rows": compact, "names": names, "shares": shares, "mcap": mcap})
    log.info("inst deals: %d rows, %d stocks", len(compact), len(syms))


# ---------------- FII / DII flows ----------------
def cash_flows(n):
    """Latest FII/DII cash-market buy/sell/net (₹ cr). NSE only serves the most recent day."""
    out = {}
    try:
        data = n.get("/api/fiidiiTradeReact") or []
    except Exception as e:
        log.warning("fiidii: %s", e)
        return None, None
    day = None
    for r in data:
        cat = (r.get("category") or "").upper()
        key = "fii" if "FII" in cat or "FPI" in cat else "dii" if "DII" in cat else None
        if not key:
            continue
        day = _d(r.get("date")) or day
        out[key] = {"buy": _f(r.get("buyValue")), "sell": _f(r.get("sellValue")), "net": _f(r.get("netValue"))}
    return (day, out) if day and out else (None, None)


FO_ROWS = {"INDEX FUTURES": "idx_fut", "INDEX OPTIONS": "idx_opt", "STOCK FUTURES": "stk_fut",
           "STOCK OPTIONS": "stk_opt", "NIFTY FUTURES": "nifty_fut", "BANKNIFTY FUTURES": "bank_fut"}


def fii_derivatives(n, d: date):
    """FII buy/sell (₹ cr) and end-of-day OI per derivative segment, from NSE's fii_stats xls."""
    url = f"https://nsearchives.nseindia.com/content/fo/fii_stats_{d.strftime('%d-%b-%Y')}.xls"
    try:
        raw = n.get(url, raw=True, tries=1)
    except Exception:
        return None
    try:
        import xlrd
        sh = xlrd.open_workbook(file_contents=raw).sheet_by_index(0)
    except Exception as e:
        log.warning("fii_stats %s: %s", d, e)
        return None
    out = {}
    for i in range(sh.nrows):
        row = sh.row_values(i)
        key = FO_ROWS.get(str(row[0]).strip().upper())
        if not key or len(row) < 7:
            continue
        buy, sell = _f(row[2]), _f(row[4])
        out[key] = {"buy": buy, "sell": sell, "net": round(buy - sell, 2) if buy is not None and sell is not None else None,
                    "oi": _f(row[5]), "oi_cr": _f(row[6])}
    return out or None


POI_COLS = {"Future Index Long": "fi_l", "Future Index Short": "fi_s", "Future Stock Long": "fs_l",
            "Future Stock Short": "fs_s", "Option Index Call Long": "ic_l", "Option Index Put Long": "ip_l",
            "Option Index Call Short": "ic_s", "Option Index Put Short": "ip_s"}


def participant_oi(n, d: date):
    """Contracts held long/short by Client, DII, FII and Pro in index/stock futures and index options."""
    url = f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d.strftime('%d%m%Y')}.csv"
    try:
        text = n.get(url, raw=True, tries=1).decode("utf-8-sig", errors="ignore")
    except Exception:
        return None
    lines = [l for l in text.splitlines() if l.strip()]
    hdr_i = next((i for i, l in enumerate(lines) if l.startswith("Client Type")), None)
    if hdr_i is None:
        return None
    rdr = csv.DictReader(io.StringIO("\n".join(lines[hdr_i:])))
    out = {}
    for r in rdr:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        who = r.get("Client Type", "")
        if who not in ("Client", "DII", "FII", "Pro"):
            continue
        out[who] = {short: _f(r.get(col)) for col, short in POI_COLS.items()}
    return out or None


def update_flows(n, path, days, jload, jsave):
    """Add derivatives data for the given dates and today's cash flows to flows.json."""
    flows = jload(path, {})
    for d in days:
        if d.weekday() >= 5:
            continue
        k = d.isoformat()
        cur = flows.get(k, {})
        if not cur.get("fo"):
            fo = fii_derivatives(n, d)
            if fo:
                cur["fo"] = fo
        if not cur.get("poi"):
            poi = participant_oi(n, d)
            if poi:
                cur["poi"] = poi
        if cur:
            flows[k] = cur
    cday, cash = cash_flows(n)
    if cday:
        flows.setdefault(cday.isoformat(), {})["cash"] = cash
    keep = sorted(flows)[-FLOW_KEEP:]
    flows = {k: flows[k] for k in keep}
    jsave(path, flows)
    log.info("flows: %d days, cash for %s", len(flows), cday)
    return flows
