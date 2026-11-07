"""Investment ideas (1-year horizon) and industry themes, built from data the desk already collects.

Stock ideas
-----------
Gates (all must pass):
  * market cap >= MIN_MCAP_CR
  * profitable over the last 12 months, and the latest quarter has a year-ago quarter to compare
  * latest results not older than the previous quarter-end (e.g. Jun-26 results are fine in the Sep-26 season)
  * no red flag, rating downgrade or large penalty (>= 0.5% of market cap) in the last FLAG_DAYS days

Score out of 100, in five groups:
  Earnings 40   latest quarter YoY: sales (8), net profit (12); previous quarter YoY (8);
                operating margin change YoY (8); profit quality: other income and one-offs small (4)
  Orders 15     order wins in the last 90 days as % of 12-month revenue (30% = full marks)
  Ownership 20  promoter stake change (8), FII + DII stake change (12), latest quarter
  Inst. buying 10  net FII/DII/fund buying in bulk/block deals, 90 days, as % of market cap (1% = full)
  Valuation 15  P/E against profit growth, growth capped at 40% (P/E <= growth = full, P/E >= 2.5x growth = 0);
                P/E > 80 = 0. P/E is trailing 12 months, or the run-rate P/E (market cap / last two quarters'
                profit x 2) when lower and growth is proven: profit up 25%+ YoY in both quarters, sales up
                15%+, profitable a year ago, and no one-off / other-income flag.

An idea needs a score >= IDEA_SCORE and at least 3 of the 5 groups at half marks or better,
so one strong signal on its own never makes an idea.

Themes
------
Stocks are grouped into themes (themes.csv) by NSE industry. Each theme gets: order wins (90 days),
share of companies with profit up 20%+ YoY, average FII + DII stake change, net institutional
buying, and how many of its stocks are ideas. The theme score ranks themes against each other:
profit-growth share 35, orders as % of theme revenue 25, FII + DII stake change 25, net institutional
buying as % of the theme's market cap 15 (percentile ranks; none at all scores 0 for orders and buying).
An order is ignored as a probable misread only if it is above 3x the company's yearly revenue AND above
1.5x its market cap.

Track record
------------
Every idea is logged with the close on the day it first appeared (ideas_log.json). Its return is
followed for a year whether or not it stays an idea, against the Nifty 500 over the same dates, and
snapshotted at 3, 6 and 12 months.

Price confirmation (optional)
-----------------------------
If SUPABASE_URL and SUPABASE_SERVICE_KEY are set, Sector Strength's latest stock and sector data is
read from the shared `docs` table and each idea gets a timing label (Ready / Building / Wait), which
is also logged so the track record can show whether the label helps. The website works out the
same label live in the browser, so the secrets are only needed for the log and the email.
"""
import json
import logging
import os
import statistics
import urllib.request
from datetime import date, timedelta

import industry

log = logging.getLogger("ideas")

MIN_MCAP_CR = 500
IDEA_SCORE = 65
HALF_GROUPS = 3
FLAG_DAYS = 180
WINDOW_DAYS = 90
BIG_PENALTY_PCT = 0.5
MAX_ORDER_PCT_REV = 300     # one order above 3x yearly revenue is usually a misread amount ...
MAX_ORDER_PCT_MCAP = 150    # ... unless it is also small against the market cap (a long-cycle order, e.g. shipbuilding)
LOG_DAYS = 400
MIN_THEME_STOCKS = 8         # smaller groups (often unmapped industries) get no theme card
GROUPS = {"earn": 40, "orders": 15, "own": 20, "inst": 10, "val": 15}
GROUP_NAMES = {"earn": "Earnings", "orders": "Orders", "own": "Ownership", "inst": "Inst. buying", "val": "Valuation"}
MAX_PE = 80
RR_PROFIT_YOY = 25          # run-rate P/E only after two quarters of profit up 25%+ YoY ...
RR_SALES_YOY = 15           # ... and sales up 15%+ in the latest quarter
G_CAP = 40                  # growth above 40% a year is not trusted to last when judging P/E
HORIZONS = (("3m", 91), ("6m", 182), ("12m", 365))


# ---------- small helpers ----------
def lin(x, lo, hi, pts):
    """0 at lo, full points at hi, straight line between (works for hi < lo too)."""
    if x is None:
        return 0.0
    t = (x - lo) / (hi - lo)
    return round(max(0.0, min(1.0, t)) * pts, 1)


def growth(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def months(p):
    if not p or not p.get("s") or not p.get("e"):
        return None
    return round((date.fromisoformat(p["e"]) - date.fromisoformat(p["s"])).days / 30.44)


def prev_qe(iso):
    d = date.fromisoformat(iso)
    m, y = d.month - 3, d.year
    if m <= 0:
        m, y = m + 12, y - 1
    return date(y, m, {3: 31, 6: 30, 9: 30, 12: 31}[m]).isoformat()


def year_ago(iso):
    return f"{int(iso[:4]) - 1}{iso[4:]}"


def r1(v):
    return None if v is None else round(v, 1)


# ---------- inputs ----------
class Inputs:
    def __init__(self, data_dir, cache_dir, jload, jsave, close=None, close_date=None):
        self.data, self.cache, self.jload, self.jsave = data_dir, cache_dir, jload, jsave
        fdir = os.path.join(data_dir, "fund")
        self.fund = {}
        for f in sorted(os.listdir(fdir)) if os.path.isdir(fdir) else []:
            if f.endswith(".json") and f != "prices.json":
                self.fund.update(jload(os.path.join(fdir, f), {}))
        pr = jload(os.path.join(fdir, "prices.json"), {})
        self.close = dict(close) if close else dict(pr.get("p") or {})
        self.close_date = close_date or pr.get("d")
        # holdings: latest season first, older seasons fill gaps
        hdir = os.path.join(data_dir, "holdings")
        self.hold = {}
        for f in sorted(os.listdir(hdir)) if os.path.isdir(hdir) else []:
            if f.endswith(".json"):
                for s, r in (jload(os.path.join(hdir, f), {}).get("rows") or {}).items():
                    self.hold[s] = r          # later files overwrite earlier ones
        self.inst = jload(os.path.join(data_dir, "inst_deals.json"), None)
        self._events()

    def _events(self):
        """Tagged announcements kept beyond the day files' 120 days (orders, red flags, penalties, ratings)."""
        path = os.path.join(self.cache, "ideas_events.json")
        ev = self.jload(path, {})
        self.ann_ind = {}
        ddir = os.path.join(self.data, "days")
        days = sorted(f[:10] for f in os.listdir(ddir) if f.endswith(".json")) if os.path.isdir(ddir) else []
        self.last_day = days[-1] if days else None
        for d in days:
            day = self.jload(os.path.join(ddir, f"{d}.json"), {})
            for a in day.get("announcements") or []:
                if a.get("ind") and a["ind"] != "-" and a.get("sym"):
                    self.ann_ind[a["sym"]] = a["ind"]
                if a.get("tag") not in ("Order", "RedFlag", "Penalty", "Rating") or not a.get("sym"):
                    continue
                if a["tag"] == "Rating" and not a.get("dir"):
                    continue
                key = str(a.get("id") or f'{d}|{a["sym"]}|{a.get("subj")}')
                ev[key] = {"d": d, "sym": a["sym"], "tag": a["tag"], "v": a.get("value_cr"),
                           "dir": a.get("dir"), "subj": (a.get("subj") or "")[:80],
                           "text": (a.get("text") or "")[:160], "pdf": a.get("pdf")}
        cut = (date.today() - timedelta(days=LOG_DAYS)).isoformat()
        ev = {k: v for k, v in ev.items() if v["d"] >= cut}
        self.jsave(path, ev)
        self.events = {}
        for v in ev.values():
            self.events.setdefault(v["sym"], []).append(v)

    def mcap(self, sym):
        r, px = self.fund.get(sym) or {}, self.close.get(sym)
        return round(r["sh"] * px / 1e7, 0) if r.get("sh") and px else None

    def inst_net(self, since):
        """{sym: (net ₹ cr, bought, sold, buyers)} from institutional bulk/block deals since a date."""
        out = {}
        if not self.inst:
            return out
        for dt, _kind, sym, client, side, _qty, _px, val, _type in self.inst.get("rows", []):
            if dt < since or val is None:
                continue
            o = out.setdefault(sym, [0.0, 0.0, 0.0, set()])
            if side == "BUY":
                o[1] += val
                o[3].add(client)
            else:
                o[2] += val
            o[0] = o[1] - o[2]
        return {s: (round(a, 2), round(b, 2), round(c, 2), len(d)) for s, (a, b, c, d) in out.items()}


# ---------- one stock ----------
def season_of(fund):
    """The quarter-end most recently reported by a meaningful number of companies."""
    counts = {}
    for r in fund.values():
        if r.get("qe"):
            counts[r["qe"]] = counts.get(r["qe"], 0) + 1
    big = [q for q, n in counts.items() if n >= 150]
    return max(big) if big else (max(counts) if counts else None)


def prev_quarter_yoy(rec):
    """Sales and profit growth YoY for the quarter before the latest one."""
    qe = rec.get("qe")
    if not qe:
        return None, None
    pq_e = prev_qe(qe)
    qs = {q["e"]: q for q in rec.get("qs") or []}
    a, b = qs.get(pq_e), qs.get(year_ago(pq_e))
    if a and b:
        return growth(a.get("rev"), b.get("rev")), growth(a.get("pat"), b.get("pat"))
    # Sep quarter: previous quarter = Apr-Jun; last year's Apr-Jun = last year's half year - last year's Jul-Sep
    pq, py, ytd_py = rec.get("pq"), rec.get("py"), rec.get("ytd_py")
    if pq and py and ytd_py and months(ytd_py) == 6:
        prev_rev = None if None in (ytd_py.get("rev"), py.get("rev")) else ytd_py["rev"] - py["rev"]
        prev_pat = None if None in (ytd_py.get("pat"), py.get("pat")) else ytd_py["pat"] - py["pat"]
        if prev_rev and prev_rev > 0:
            return growth(pq.get("rev"), prev_rev), growth(pq.get("pat"), prev_pat)
    return None, None


def score_stock(sym, rec, mcap, hold, orders, inst):
    """(score, groups, details, flags) for one stock that passed the gates."""
    q, py, ttm = rec.get("q") or {}, rec.get("py") or {}, rec.get("ttm") or {}
    flags, det = [], {}
    fin = bool(rec.get("finco"))

    # earnings
    s_yoy = growth(q.get("rev"), py.get("rev"))
    p_yoy = growth(q.get("pat"), py.get("pat"))
    turn = (py.get("pat") is not None and py["pat"] <= 0 < (q.get("pat") or 0))
    e = lin(s_yoy, 0, 20, 8)
    e += 12 if turn else lin(p_yoy, 0, 30, 12)
    if turn:
        flags.append("Turnaround")
    ps, pp_ = prev_quarter_yoy(rec)
    if ps is None and pp_ is None:
        flags.append("1 quarter YoY only")
    else:
        e += lin(ps, 0, 20, 3) + lin(pp_, 0, 30, 5)
    if fin:
        m_now = q["pat"] / q["rev"] * 100 if q.get("rev") and q.get("pat") is not None else None
        m_old = py["pat"] / py["rev"] * 100 if py.get("rev") and py.get("pat") is not None else None
    else:
        m_now = q["op"] / q["rev"] * 100 if q.get("rev") and q.get("op") is not None else None
        m_old = py["op"] / py["rev"] * 100 if py.get("rev") and py.get("op") is not None else None
    dm = None if m_now is None or m_old is None else m_now - m_old
    e += lin(dm, -1, 2, 8)
    pbt = q.get("pbt")
    qual = 0
    if pbt and pbt > 0:
        oi_share = (q.get("oi") or 0) / pbt
        exc_share = abs(q.get("exc") or 0) / pbt
        qual = (2 if oi_share <= 0.25 else 0) + (2 if exc_share <= 0.10 else 0)
        if oi_share > 0.5:
            flags.append("Profit mostly other income")
        if exc_share > 0.25:
            flags.append("Large one-off items")
    e += qual
    det.update(sales_yoy=s_yoy, pat_yoy=p_yoy, prev_sales_yoy=ps, prev_pat_yoy=pp_,
               margin=r1(m_now), margin_chg=r1(dm), margin_kind="net" if fin else "operating")

    # orders: last 90 days, as % of 12-month revenue
    o_val = sum(v for v in orders if v) if orders else 0
    o_pct = o_val / ttm["rev"] * 100 if ttm.get("rev") and o_val else None
    o = lin(o_pct, 0, 30, 15)
    det.update(orders_n=len(orders), orders_cr=round(o_val, 1) if o_val else None, orders_pct_rev=r1(o_pct))

    # ownership: latest shareholding quarter
    w = 0.0
    if hold:
        pc = hold.get("promoter_chg")
        if hold.get("promoter") in (None, 0):
            w += 5      # no promoter (professionally run company): neutral
        elif pc is None:
            w += 3
        else:
            w += 8 if pc >= 0.5 else 5 if pc >= -0.1 else 2 if pc >= -1 else 0
        ic = None
        if hold.get("fii_chg") is not None or hold.get("dii_chg") is not None:
            ic = (hold.get("fii_chg") or 0) + (hold.get("dii_chg") or 0)
            w += lin(ic, -0.5, 2.0, 12)
        det.update(hold_qe=hold.get("qe"), promoter=hold.get("promoter"), promoter_chg=pc,
                   fii_chg=hold.get("fii_chg"), dii_chg=hold.get("dii_chg"), mf_chg=hold.get("mf_chg"),
                   inst_stake_chg=r1(ic) if ic is not None else None)
    else:
        flags.append("No shareholding data")

    # institutional buying in bulk/block deals
    i = 0.0
    if inst:
        net, bought, sold, nb = inst
        ipct = net / mcap * 100 if mcap else None
        if net >= 2:
            i = lin(ipct, 0, 1.0, 10)
        det.update(inst_net_cr=net, inst_bought_cr=bought, inst_sold_cr=sold, inst_buyers=nb, inst_pct_mcap=r1(ipct))

    # valuation: P/E against growth. Trailing P/E overstates the price of a fast grower (the 12 months
    # include older, smaller quarters), so when growth is proven the run-rate P/E is used if lower.
    pe_ttm = mcap / ttm["pat"] if mcap and ttm.get("pat") else None
    pq = rec.get("pq") or {}
    pe_rr = None
    if (mcap and q.get("pat") is not None and pq.get("pat") is not None and (py.get("pat") or 0) > 0
            and (p_yoy or 0) >= RR_PROFIT_YOY and (pp_ or 0) >= RR_PROFIT_YOY and (s_yoy or 0) >= RR_SALES_YOY
            and "Large one-off items" not in flags and "Profit mostly other income" not in flags):
        rr_profit = (q["pat"] + pq["pat"]) * 2
        if rr_profit > 0:
            pe_rr = mcap / rr_profit
    use_rr = pe_rr is not None and (pe_ttm is None or pe_rr < pe_ttm)
    pe = pe_rr if use_rr else pe_ttm
    ytd, ytd_py = rec.get("ytd") or {}, rec.get("ytd_py") or {}
    g = growth(ytd.get("pat"), ytd_py.get("pat")) if ytd and ytd_py and (months(rec.get("ytd")) or 0) >= 6 else p_yoy
    if turn:
        g = 30.0
    v = 0.0
    if pe and pe <= MAX_PE:
        if g is None or g <= 5:
            v = lin(pe, 25, 10, 6)        # little growth: only cheap shares score, and only partly
        else:
            peg = pe / min(g, G_CAP)
            v = lin(peg, 2.5, 1.0, 15)
    det.update(pe=r1(pe), pe_ttm=r1(pe_ttm), pe_rr=r1(pe_rr), pe_basis="RR" if use_rr else "TTM",
               growth_used=r1(g), peg=r1(pe / min(g, G_CAP)) if pe and g and g > 5 else None)

    groups = {"earn": round(e, 1), "orders": round(o, 1), "own": round(w, 1), "inst": round(i, 1), "val": round(v, 1)}
    return round(sum(groups.values()), 1), groups, det, flags


# ---------- Sector Strength (optional) ----------
def load_sector_strength():
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return None
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    q = f"{url.rstrip('/')}/rest/v1/docs?select=key,data,updated_at&key=in.(ss_stocks,ss_sectors,ss_regime)"
    try:
        with urllib.request.urlopen(urllib.request.Request(q, headers=headers), timeout=60) as r:
            rows = json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        log.warning("Sector Strength data not read: %s", e)
        return None
    return {r["key"][3:]: r["data"] for r in rows}


def timing_label(ss_stock):
    """Same rule as the website: fundamentals decide what to buy, price decides when."""
    if not ss_stock or ss_stock.get("rs_rating") is None:
        return "No price data"
    rs, above, rising = ss_stock.get("rs_rating"), ss_stock.get("above_200"), ss_stock.get("200_rising")
    if rs >= 70 and above:
        return "Ready"
    if above is False and rising is False:
        return "Wait"
    return "Building"


# ---------- build ----------
def build(data_dir, cache_dir, jload, jsave, close=None, close_date=None, bench_close=None, ss=None):
    inp = Inputs(data_dir, cache_dir, jload, jsave, close, close_date)
    as_of = inp.close_date or inp.last_day or date.today().isoformat()
    today = date.fromisoformat(as_of)
    since = (today - timedelta(days=WINDOW_DAYS - 1)).isoformat()
    flag_since = (today - timedelta(days=FLAG_DAYS)).isoformat()
    season = season_of(inp.fund)
    oldest_ok = prev_qe(season) if season else None
    inst = inp.inst_net(since)
    themes_rows, lookup = industry.load_themes()
    ind_map = jload(os.path.join(cache_dir, "industry.json"), {})
    ss_stocks = (ss or {}).get("stocks", {}).get("stocks", {}) if ss else {}

    scored, excluded = [], {}
    universe = []          # passed the size gate: used for themes
    for sym, rec in inp.fund.items():
        mc = inp.mcap(sym)
        if not mc or mc < MIN_MCAP_CR:
            continue
        theme = industry.theme_of(ind_map.get(sym), inp.ann_ind.get(sym), lookup)
        ev = inp.events.get(sym, [])
        orders = [x["v"] for x in ev if x["tag"] == "Order" and x["d"] >= since and x.get("v")]
        ttm = rec.get("ttm") or {}
        # dropped only when above 3x revenue AND above 1.5x market cap (both look like a misread amount)
        orders = [v for v in orders if not (ttm.get("rev") and v / ttm["rev"] * 100 > MAX_ORDER_PCT_REV
                                            and v / mc * 100 > MAX_ORDER_PCT_MCAP)]
        base = {"sym": sym, "name": rec.get("n"), "mcap": mc, "theme": theme, "qe": rec.get("qe"),
                "close": inp.close.get(sym)}
        universe.append((base, rec, orders))
        why = None
        q, py = rec.get("q") or {}, rec.get("py") or {}
        if not q or not py or q.get("pat") is None or py.get("pat") is None:
            why = "No year-ago quarter to compare"
        elif not ttm.get("pat") or ttm["pat"] <= 0:
            why = "Loss over the last 12 months"
        elif oldest_ok and (rec.get("qe") or "") < oldest_ok:
            why = "Results out of date"
        else:
            bad = [x for x in ev if x["d"] >= flag_since and (
                x["tag"] == "RedFlag" or (x["tag"] == "Rating" and x.get("dir") == "down") or
                (x["tag"] == "Penalty" and x.get("v") and x["v"] >= mc * BIG_PENALTY_PCT / 100))]
            if bad:
                b = max(bad, key=lambda x: x["d"])
                why = {"RedFlag": "Red flag", "Rating": "Rating downgrade", "Penalty": "Large penalty"}[b["tag"]] + f' ({b["d"]})'
        if why:
            excluded[why.split(" (")[0]] = excluded.get(why.split(" (")[0], 0) + 1
            continue
        score, groups, det, flags = score_stock(sym, rec, mc, inp.hold.get(sym), orders, inst.get(sym))
        small_pen = [x for x in ev if x["tag"] == "Penalty" and x["d"] >= flag_since]
        if small_pen:
            flags.append(f"{len(small_pen)} small penalt{'y' if len(small_pen) == 1 else 'ies'} (180d)")
        if rec.get("qe") and season and rec["qe"] < season:
            flags.append(f"{season[:7]} results not out yet")
        half = sum(1 for k, v in groups.items() if v >= GROUPS[k] / 2)
        row = {**base, "score": score, "groups": groups, "half": half, **det, "flags": flags,
               "filing": rec.get("x"), "nat": rec.get("nat")}
        if ss_stocks:
            row["label"] = timing_label(ss_stocks.get(sym))
        scored.append(row)

    scored.sort(key=lambda r: -r["score"])
    ideas = [r for r in scored if r["score"] >= IDEA_SCORE and r["half"] >= HALF_GROUPS]
    idea_syms = {r["sym"] for r in ideas}
    near = [r for r in scored if r["sym"] not in idea_syms and r["score"] >= IDEA_SCORE - 12][:40]
    for i, r in enumerate(scored):
        r["rank"] = i + 1

    themes = build_themes(universe, scored, idea_syms, inst, themes_rows, ss)
    log_out = update_log(data_dir, jload, jsave, as_of, ideas, inp.close, bench_close)
    out = {
        "as_of": as_of, "season": season,
        "rules": {"min_mcap_cr": MIN_MCAP_CR, "idea_score": IDEA_SCORE, "half_groups": HALF_GROUPS,
                  "window_days": WINDOW_DAYS, "flag_days": FLAG_DAYS, "groups": GROUPS, "group_names": GROUP_NAMES},
        "counts": {"universe": len(universe), "scored": len(scored), "ideas": len(ideas), "excluded": excluded,
                   "with_industry": sum(1 for b, _, _ in universe if b["theme"])},
        "ideas": ideas, "near": near, "themes": themes,
        "new": log_out["new"], "dropped": log_out["dropped"], "record": log_out["record"],
        "ss_used": bool(ss_stocks),
    }
    jsave(os.path.join(data_dir, "ideas.json"), out)
    log.info("ideas: %d stocks >= ₹%d cr, %d scored, %d ideas, %d themes", len(universe), MIN_MCAP_CR,
             len(scored), len(ideas), len(themes))
    print(f"::notice title=Ideas::{len(ideas)} ideas from {len(scored)} scored stocks; "
          f"new {len(log_out['new'])}, dropped {len(log_out['dropped'])}; {len(themes)} themes")
    return out


def build_themes(universe, scored, idea_syms, inst, themes_rows, ss):
    ss_index = {t: k for t, k, _ in themes_rows}
    score_of = {r["sym"]: r for r in scored}
    by = {}
    for base, rec, orders in universe:
        if base["theme"]:
            by.setdefault(base["theme"], []).append((base, rec, orders))
    rows = []
    for theme, items in by.items():
        if len(items) < MIN_THEME_STOCKS:
            continue
        rev = sum((rec.get("ttm") or {}).get("rev") or 0 for _, rec, _ in items)
        o_n = sum(len(o) for _, _, o in items)
        o_val = sum(sum(o) for _, _, o in items)
        growths = [growth((rec.get("q") or {}).get("pat"), (rec.get("py") or {}).get("pat")) for _, rec, _ in items]
        growths = [g for g in growths if g is not None]
        strong = sum(1 for g in growths if g >= 20)
        sales = [growth((rec.get("q") or {}).get("rev"), (rec.get("py") or {}).get("rev")) for _, rec, _ in items]
        sales = [s for s in sales if s is not None]
        stake = [score_of[b["sym"]].get("inst_stake_chg") for b, _, _ in items if b["sym"] in score_of]
        stake = [s for s in stake if s is not None]
        inet = sum(inst[b["sym"]][0] for b, _, _ in items if b["sym"] in inst)
        tmcap = sum(b["mcap"] or 0 for b, _, _ in items)
        top = sorted((score_of[b["sym"]] for b, _, _ in items if b["sym"] in score_of), key=lambda r: -r["score"])[:6]
        rows.append({
            "theme": theme, "n": len(items), "ss_index": ss_index.get(theme) or None,
            "orders_n": o_n, "orders_cr": round(o_val, 0), "orders_pct_rev": r1(o_val / rev * 100) if rev else None,
            "reported": len(growths), "strong": strong, "strong_pct": r1(strong / len(growths) * 100) if growths else None,
            "median_sales_yoy": r1(statistics.median(sales)) if sales else None,
            "stake_chg": round(statistics.mean(stake), 2) if stake else None,
            "stake_up_pct": r1(sum(1 for s in stake if s > 0) / len(stake) * 100) if stake else None,
            "inst_net_cr": round(inet, 0), "inst_net_pct_mcap": round(inet / tmcap * 100, 3) if tmcap else None,
            "ideas": sorted(b["sym"] for b, _, _ in items if b["sym"] in idea_syms),
            "top": [{"sym": r["sym"], "score": r["score"]} for r in top],
        })
    # theme score: percentile ranks against other themes
    def pr(key, zero_is_nothing):
        """Mid-rank percentile (ties share the middle). For orders and buying, none at all scores 0."""
        vals = [r[key] for r in rows if r[key] is not None]
        for r in rows:
            v = r[key]
            if v is None or not vals or (zero_is_nothing and v <= 0):
                p = 0.0
            else:
                p = (sum(1 for x in vals if x < v) + 0.5 * sum(1 for x in vals if x == v)) / len(vals)
            r.setdefault("_p", {})[key] = p
    # institutional buying is ranked as % of the theme's market cap, so a theme with many stocks gets no head start
    for k, z in (("strong_pct", False), ("orders_pct_rev", True), ("stake_chg", False), ("inst_net_pct_mcap", True)):
        pr(k, z)
    for r in rows:
        p = r.pop("_p")
        r["score"] = round(35 * p["strong_pct"] + 25 * p["orders_pct_rev"] + 25 * p["stake_chg"]
                           + 15 * p["inst_net_pct_mcap"], 0)
        if ss and r["ss_index"]:
            sec = (((ss.get("sectors") or {}).get("benchmarks") or {}).get("NIFTY500") or {}).get("rows", {}).get(r["ss_index"])
            if sec:
                r["ss_rank"], r["ss_quadrant"] = sec.get("rank"), sec.get("quadrant")
    rows.sort(key=lambda r: -r["score"])
    return rows


# ---------- track record ----------
def update_log(data_dir, jload, jsave, as_of, ideas, close, bench_close):
    path = os.path.join(data_dir, "ideas_log.json")
    lg = jload(path, {"days": {}, "bench": {}, "entries": []})
    if bench_close:
        lg["bench"][as_of] = bench_close
    syms = [r["sym"] for r in ideas]
    lg["days"][as_of] = syms
    lg["entries"] = [e for e in lg["entries"] if not (e["first"] == as_of and e["sym"] not in syms)]
    prev_days = sorted(d for d in lg["days"] if d < as_of)
    prev = set(lg["days"][prev_days[-1]]) if prev_days else set()
    cur = set(syms)
    by_sym = {r["sym"]: r for r in ideas}
    new = [] if not prev_days else sorted(cur - prev, key=lambda s: -by_sym[s]["score"])
    dropped = sorted(prev - cur) if prev_days else []
    # entries: one per spell as an idea; a stock that comes back after 30+ days opens a new entry
    open_by = {}
    for e in lg["entries"]:
        if e["sym"] not in open_by or e["first"] > open_by[e["sym"]]["first"]:
            open_by[e["sym"]] = e
    for s in syms:
        e = open_by.get(s)
        gap = (date.fromisoformat(as_of) - date.fromisoformat(e["last"])).days if e else None
        if e and gap is not None and gap <= 30:
            e["last"] = as_of
            continue
        if close.get(s):
            r = by_sym[s]
            lg["entries"].append({"sym": s, "first": as_of, "last": as_of, "px": close[s], "score": r["score"],
                                  "theme": r.get("theme"), "label": r.get("label"),
                                  "bench": bench_close, "h": {}})
    # returns and horizon snapshots
    for e in lg["entries"]:
        px = close.get(e["sym"])
        if not px or not e.get("px"):
            continue
        e["ret"] = round((px / e["px"] - 1) * 100, 1)
        if e.get("bench") and bench_close:
            e["bret"] = round((bench_close / e["bench"] - 1) * 100, 1)
        age = (date.fromisoformat(as_of) - date.fromisoformat(e["first"])).days
        e["age"] = age
        for k, days in HORIZONS:
            if age >= days and k not in e["h"]:
                e["h"][k] = {"ret": e["ret"], "bret": e.get("bret"), "d": as_of}
    cut = (date.fromisoformat(as_of) - timedelta(days=LOG_DAYS)).isoformat()
    lg["days"] = {d: v for d, v in lg["days"].items() if d >= cut}
    lg["bench"] = {d: v for d, v in lg["bench"].items() if d >= cut}
    lg["entries"] = [e for e in lg["entries"] if e["first"] >= cut]
    jsave(path, lg)
    return {"new": new, "dropped": dropped, "record": summarise(lg["entries"])}


def summarise(entries):
    def stats(es, key="ret", bkey="bret"):
        rs = [e[key] for e in es if e.get(key) is not None]
        ex = [e[key] - e[bkey] for e in es if e.get(key) is not None and e.get(bkey) is not None]
        return {"n": len(rs), "avg": r1(statistics.mean(rs)) if rs else None,
                "excess": r1(statistics.mean(ex)) if ex else None,
                "beat_pct": r1(sum(1 for x in ex if x > 0) / len(ex) * 100) if ex else None,
                "win_pct": r1(sum(1 for x in rs if x > 0) / len(rs) * 100) if rs else None}
    out = {"all": stats(entries), "by_label": {}, "horizons": {}}
    for lab in sorted({e.get("label") for e in entries if e.get("label")}):
        out["by_label"][lab] = stats([e for e in entries if e.get("label") == lab])
    for k, _ in HORIZONS:
        hs = [e["h"][k] for e in entries if k in e.get("h", {})]
        out["horizons"][k] = stats(hs)
    out["entries"] = sorted(({k: e.get(k) for k in ("sym", "first", "last", "px", "score", "theme", "label", "ret", "bret", "age")}
                             for e in entries), key=lambda e: e["first"], reverse=True)[:300]
    return out
