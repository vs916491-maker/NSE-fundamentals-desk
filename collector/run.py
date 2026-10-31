"""Daily NSE fundamentals collector.

Usage:
  python collector/run.py                       # today (IST)
  python collector/run.py --date 2026-10-23     # one day
  python collector/run.py --backfill 2026-10-01 2026-10-23
  python collector/run.py --email               # also send the digest (once per day)
"""
import argparse, csv, io, json, logging, os, sys, time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
from nse import NSE
import tagger, xbrl, flows, clients, fundamentals

IST = ZoneInfo("Asia/Kolkata")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "site", "data")
CACHE = os.path.join(ROOT, "cache")
KEEP_DAYS = 120
IF_FIN = "Integrated Filing- Financials"

log = logging.getLogger("run")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ---------- small helpers ----------
def jload(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def jsave(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False, default=str)
    os.replace(tmp, path)


def nse_date(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def parse_nse_date(s):
    """'30-SEP-2026', '24-Oct-2026 12:57:34', '24-10-2026' or '2026-10-24' -> date."""
    s = (s or "").strip()
    try:
        return datetime.strptime(s[:11].title(), "%d-%b-%Y").date()
    except ValueError:
        pass
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def growth(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def prev_qe(qe: date) -> date:
    """Latest quarter-end strictly before qe (works for non-quarter-end dates too)."""
    y, m = qe.year, qe.month
    for _ in range(5):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        if m in (3, 6, 9, 12):
            last = {3: 31, 6: 30, 9: 30, 12: 31}[m]
            if date(y, m, last) < qe:
                return date(y, m, last)
    return date(qe.year - 1, 12, 31)


def year_ago(qe: date) -> date:
    return date(qe.year - 1, qe.month, qe.day)


class Budget:
    def __init__(self, minutes):
        self.end = time.time() + minutes * 60

    def ok(self):
        return time.time() < self.end


# ---------- collector ----------
class Collector:
    def __init__(self, budget_min=40):
        self.n = NSE()
        self.budget = Budget(budget_min)
        self.close = {}
        self.turnover = {}
        self.close_date = None
        self.cache_dir = CACHE

    # ----- prices (bhavcopy) -----
    def load_close(self, d: date):
        for i in range(0, 7):
            dd = d - timedelta(days=i)
            url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{dd.strftime('%d%m%Y')}.csv"
            try:
                raw = self.n.get(url, raw=True, tries=2).decode(errors="ignore")
            except Exception:
                continue
            rows = csv.reader(io.StringIO(raw))
            hdr = [h.strip() for h in next(rows)]
            si, se, ci = hdr.index("SYMBOL"), hdr.index("SERIES"), hdr.index("CLOSE_PRICE")
            ti = hdr.index("TURNOVER_LACS") if "TURNOVER_LACS" in hdr else None
            for r in rows:
                if len(r) > ci and r[se].strip() in ("EQ", "BE", "BZ", "SM", "ST"):
                    try:
                        self.close[r[si].strip()] = float(r[ci])
                        if ti is not None:
                            self.turnover[r[si].strip()] = float(r[ti] or 0)
                    except ValueError:
                        pass
            self.close_date = dd.isoformat()
            log.info("bhavcopy %s: %d prices", dd, len(self.close))
            return
        log.warning("no bhavcopy found near %s", d)

    # ----- shareholding cache -----
    def shp_history(self, sym):
        """{qe_iso: parsed shp} for the symbol, fetching missing quarters lazily (latest 2)."""
        path = os.path.join(CACHE, "shp", f"{sym}.json")
        cache = jload(path, {})
        return cache, path

    def shp_for(self, sym, qe: date = None, listing=None):
        cache, path = self.shp_history(sym)
        key = qe.isoformat() if qe else None
        if key and (cache.get(key) or {}).get("_v") == xbrl.VERSION:
            return cache[key]
        if not self.budget.ok():
            return None
        try:
            if listing is None:
                listing = self.n.get("/api/corporate-share-holdings-master", {"index": "equities", "symbol": sym}) or []
        except Exception as e:
            log.warning("shp list %s: %s", sym, e)
            return None
        rows = [r for r in listing if r.get("xbrl")]
        if not rows:
            return None
        if qe:
            rows = [r for r in rows if parse_nse_date(r.get("date", "")) == qe]
            if not rows:
                return None
        r = rows[0]
        rqe = parse_nse_date(r.get("date", ""))
        try:
            doc = self.n.get(r["xbrl"], raw=True).decode(errors="ignore")
            parsed = xbrl.parse_shp(doc)
        except Exception as e:
            log.warning("shp xbrl %s: %s", sym, e)
            return None
        if rqe:
            cache[rqe.isoformat()] = parsed
            jsave(path, cache)
        return parsed

    def shares(self, sym):
        cache, _ = self.shp_history(sym)
        for k in sorted(cache, reverse=True):
            if cache[k] and cache[k].get("shares"):
                return cache[k]["shares"]
        p = self.shp_for(sym)
        return p.get("shares") if p else None

    def mcap(self, sym):
        px = self.close.get(sym)
        if px is None:
            return None
        sh = self.shares(sym)
        return round(sh * px / 1e7, 0) if sh else None

    # ----- announcements -----
    def announcements(self, d: date):
        raw = self.n.get("/api/corporate-announcements",
                         {"index": "equities", "from_date": nse_date(d), "to_date": nse_date(d)}) or []
        out = []
        for a in raw:
            subj = a.get("desc") or ""
            text = (a.get("attchmntText") or "").strip()
            t = tagger.tag(subj, text)
            item = {
                "id": a.get("seq_id"), "sym": a.get("symbol"), "name": a.get("sm_name"),
                "time": a.get("sort_date") or a.get("an_dt"), "subj": subj, "text": text[:500],
                "pdf": a.get("attchmntFile"), "ind": a.get("smIndustry"), "tag": t,
            }
            if t in ("Order", "Buyback", "Penalty"):
                v, rawv = tagger.amount(text)
                item["value_cr"], item["value_raw"] = v, rawv
            if t == "Rating":
                item["dir"] = tagger.rating_direction(text)
            out.append(item)
        # value is often only inside the PDF: read the first pages of those
        pdfs = 0
        for it in out:
            if (it["tag"] in ("Order", "Buyback", "Penalty") and not it.get("value_cr") and pdfs < 60
                    and str(it.get("pdf") or "").lower().endswith(".pdf") and self.budget.ok()):
                pdfs += 1
                txt = pdf_text(self.n, it["pdf"])
                if txt:
                    v, rawv = tagger.amount_near(txt, it["tag"])
                    if v:
                        it["value_cr"], it["value_raw"], it["value_src"] = v, rawv, "pdf"
                    elif rawv and not it.get("value_raw"):
                        it["value_raw"] = rawv
        log.info("read %d PDFs", pdfs)
        # market cap for orders & buybacks
        for it in out:
            if it["tag"] in ("Order", "Buyback") and self.budget.ok():
                mc = self.mcap(it["sym"])
                it["mcap"] = mc
                if mc and it.get("value_cr"):
                    it["pct_mcap"] = round(it["value_cr"] / mc * 100, 2)
        out.sort(key=lambda x: x.get("time") or "", reverse=True)
        log.info("announcements %s: %d", d, len(out))
        return out

    # ----- results -----
    def fin_listing(self, sym, strict=False):
        """strict: raise on a download error (instead of returning an empty list)."""
        try:
            r = self.n.get("/api/integrated-filing-results",
                           {"index": "equities", "symbol": sym, "type": IF_FIN, "size": 100}) or {}
            return r.get("data") or []
        except Exception as e:
            log.warning("fin list %s: %s", sym, e)
            if strict:
                raise
            return []

    def fin_metrics(self, sym, nature, qe: date, url, cache, accept_old=False, strict=False):
        """Parsed results for one filing (cached). accept_old: an older cached parse is fine
        (enough for the sales/profit comparison columns)."""
        key = f"{nature}|{qe.isoformat()}"
        v = (cache.get(key) or {}).get("_v")
        if key in cache and (v == xbrl.FIN_VERSION or (accept_old and v is not None)):
            return cache[key]
        try:
            doc = self.n.get(url, raw=True).decode(errors="ignore")
            m = xbrl.parse_results(doc, qe)
        except Exception as e:
            log.warning("fin xbrl %s %s: %s", sym, key, e)
            if strict:
                raise
            return None
        cache[key] = m
        return m

    def results(self, d: date):
        rows, page, seen = [], 1, set()
        while True:
            r = self.n.get("/api/integrated-filing-results",
                           {"index": "equities", "type": IF_FIN, "from_date": nse_date(d),
                            "to_date": nse_date(d), "size": 100, "page": page}) or {}
            data = r.get("data") or []
            new = [x for x in data if x.get("seq_Id") not in seen]
            for x in new:
                seen.add(x.get("seq_Id"))
            rows += new
            total = r.get("totalCount") or 0
            if not new or len(rows) >= total or page > 30:
                break
            page += 1
        log.info("results filings %s: %d", d, len(rows))

        # group by symbol, keep current quarter only
        by_sym = {}
        for x in rows:
            qe = parse_nse_date(x.get("qe_Date") or "")
            if not qe or (d - qe).days > 75 or (d - qe).days < 0:
                continue
            by_sym.setdefault(x["symbol"], []).append((qe, x))

        out = []
        for sym, items in by_sym.items():
            qe = max(q for q, _ in items)
            items = [x for q, x in items if q == qe]
            name = items[0].get("smName") or items[0].get("cmName")
            cache_path = os.path.join(CACHE, "fin", f"{sym}.json")
            cache = jload(cache_path, {})
            listing = None
            best = None
            natures = sorted({(x.get("consolidated") or "Standalone") for x in items},
                             key=lambda n: 0 if n.startswith("Cons") else 1)
            for nature in natures:
                cand = sorted([x for x in items if (x.get("consolidated") or "Standalone") == nature],
                              key=lambda x: x.get("creation_Date") or "", reverse=True)[0]
                cur = self.fin_metrics(sym, nature, qe, cand["xbrl"], cache)
                if not cur:
                    continue
                row = {"sym": sym, "name": name, "qe": qe.isoformat(), "nature": nature,
                       "filed": cand.get("creation_Date"), "audited": cand.get("audited"),
                       "revision": cand.get("type_Sub") == "Revision", "xbrl": cand.get("ixbrl") or cand.get("xbrl"),
                       **{k: cur.get(k) for k in ("rev", "pat", "pbt", "eps")}}
                # comparatives: the filing itself carries last quarter and the same quarter last year
                per = cur.get("periods") or {}
                for label in ("py", "pq"):
                    if per.get(label):
                        row[f"rev_{label}"] = per[label].get("rev")
                        row[f"pat_{label}"] = per[label].get("pat")
                if self.budget.ok() and not (per.get("py") and per.get("pq")):
                    if listing is None:
                        listing = self.fin_listing(sym)
                    hist = {}
                    for h in sorted(listing, key=lambda x: x.get("creation_Date") or ""):
                        hq = parse_nse_date(h.get("qe_Date") or "")
                        hn = h.get("consolidated") or "Standalone"
                        if hq and h.get("xbrl"):
                            hist[(hn, hq)] = h["xbrl"]  # later filings (revisions) overwrite
                    for label, pq in (("py", year_ago(qe)), ("pq", prev_qe(qe))):
                        url = hist.get((nature, pq))
                        if url and self.budget.ok() and row.get(f"rev_{label}") is None:
                            pm = self.fin_metrics(sym, nature, pq, url, cache, accept_old=True)
                            if pm:
                                row[f"rev_{label}"] = pm.get("rev")
                                row[f"pat_{label}"] = pm.get("pat")
                for lab in ("py", "pq"):  # a >20x revenue jump is almost always a unit error in one filing
                    a, b = row.get("rev"), row.get(f"rev_{lab}")
                    if a and b and (a / b > 20 or a / b < 0.05):
                        row[f"rev_{lab}"] = row[f"pat_{lab}"] = None
                        row["check"] = True
                row["rev_yoy"] = growth(row["rev"], row.get("rev_py"))
                row["pat_yoy"] = growth(row["pat"], row.get("pat_py"))
                row["rev_qoq"] = growth(row["rev"], row.get("rev_pq"))
                row["pat_qoq"] = growth(row["pat"], row.get("pat_pq"))
                row["verdict"] = verdict(row)
                if best is None or (best.get("pat_yoy") is None and best.get("rev_yoy") is None
                                    and (row.get("pat_yoy") is not None or row.get("rev_yoy") is not None)):
                    best = row
            jsave(cache_path, cache)
            if best:
                if self.budget.ok():
                    best["mcap"] = self.mcap(sym)
                out.append(best)
        log.info("results parsed %s: %d companies", d, len(out))
        return out

    # ----- shareholding -----
    def holdings(self, d: date):
        raw = self.n.get("/api/corporate-share-holdings-master",
                         {"index": "equities", "from_date": nse_date(d), "to_date": nse_date(d)}) or []
        out = []
        for r in raw:
            sym = r.get("symbol")
            qe = parse_nse_date(r.get("date", ""))
            if not sym or not qe or not r.get("xbrl") or (d - qe).days > 120:
                continue  # skip late/revised filings for old quarters
            cache, path = self.shp_history(sym)
            cur = cache.get(qe.isoformat())
            if cur and cur.get("_v") != xbrl.VERSION:
                cur = None
            if cur is None and not self.budget.ok():
                # out of time: keep the headline numbers NSE gives in the list itself
                def f(x):
                    try:
                        return float(x)
                    except (TypeError, ValueError):
                        return None
                out.append({"sym": sym, "name": r.get("name"), "qe": qe.isoformat(), "filed": r.get("broadcastDate"),
                            "xbrl": r.get("xbrl"), "promoter": f(r.get("pr_and_prgrp")), "public": f(r.get("public_val"))})
                continue
            if cur is None:
                try:
                    doc = self.n.get(r["xbrl"], raw=True).decode(errors="ignore")
                    cur = xbrl.parse_shp(doc)
                    if cur.get("mf") is None and not os.path.exists(os.path.join(CACHE, "debug_shp.json")):
                        import re as _re
                        jsave(os.path.join(CACHE, "debug_shp.json"),
                              {"sym": sym, "contexts": sorted(set(_re.findall(r'contextRef="([^"]+_ContextI)"', doc)))})
                    cache[qe.isoformat()] = cur
                    jsave(path, cache)
                except Exception as e:
                    log.warning("shp %s: %s", sym, e)
                    continue
            try:
                prev = self.shp_for(sym, prev_qe(qe))
            except Exception as e:
                log.warning("shp prev %s: %s", sym, e)
                prev = None
            row = {"sym": sym, "name": r.get("name"), "qe": qe.isoformat(), "filed": r.get("broadcastDate"),
                   "xbrl": r.get("xbrl")}
            for k in ("promoter", "fii", "dii", "mf", "public"):
                row[k] = cur.get(k)
                if prev and cur.get(k) is not None and prev.get(k) is not None:
                    row[k + "_chg"] = round(cur[k] - prev[k], 2)
            out.append(row)
        log.info("holdings %s: %d", d, len(out))
        return out

    # ----- bulk / block deals -----
    def deal_rows(self, d_to: date):
        """Bulk/block deals for the ~95 days up to d_to (fetched once per run)."""
        if getattr(self, "_deals", None) is None or self._deals_to < d_to:
            self._deals = flows.deal_history(self.n, d_to - timedelta(days=flows.DEAL_DAYS), d_to)
            self._deals_to = d_to
        return self._deals

    def deals(self, d: date):
        out = [dict(r) for r in self.deal_rows(max(d, getattr(self, "_deals_to", d))) if r["date"] == d.isoformat()]
        if not out:  # history API not updated yet: fall back to the latest-day archive file
            for kind in ("bulk", "block"):
                try:
                    raw = self.n.get(f"https://nsearchives.nseindia.com/content/equities/{kind}.csv", raw=True).decode(errors="ignore")
                except Exception as e:
                    log.warning("%s csv: %s", kind, e)
                    continue
                for row in csv.DictReader(io.StringIO(raw)):
                    row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
                    if parse_nse_date(row.get("Date", "")) != d:
                        continue
                    try:
                        qty = float(row.get("Quantity Traded", "0").replace(",", ""))
                        px = float(row.get("Trade Price / Wght. Avg. Price", "0").replace(",", ""))
                    except ValueError:
                        continue
                    client = row.get("Client Name", "")
                    t = clients.classify(client)
                    rec = {"date": d.isoformat(), "kind": kind, "sym": row.get("Symbol"), "name": row.get("Security Name"),
                           "client": client, "side": row.get("Buy/Sell", "").upper(), "qty": qty, "price": px,
                           "value_cr": round(qty * px / 1e7, 2), "itype": t, "inst": t is not None}
                    out.append(rec)
                    if getattr(self, "_deals", None) is not None:
                        self._deals.append(dict(rec))  # so the 30-day view includes today too
        for r in out:
            r.pop("date", None)
        out.sort(key=lambda x: -x["value_cr"])
        log.info("deals %s: %d", d, len(out))
        return out


def pdf_text(n, url, pages=3):
    try:
        raw = n.get(url, raw=True, tries=2)
        if not raw or len(raw) > 12_000_000:
            return ""
        from pypdf import PdfReader
        rd = PdfReader(io.BytesIO(raw))
        return " ".join((p.extract_text() or "") for p in rd.pages[:pages])
    except Exception as e:
        log.warning("pdf %s: %s", url, e)
        return ""


def verdict(r):
    py, ry = r.get("pat_yoy"), r.get("rev_yoy")
    pat, pat_py = r.get("pat"), r.get("pat_py")
    if pat is not None and pat_py is not None and pat_py < 0 < pat:
        return "Turnaround"
    if pat is not None and pat < 0:
        return "Loss"
    if py is None and ry is None:
        return None
    if (py or 0) >= 15 and (ry or 0) >= 10:
        return "Strong"
    if (py is not None and py < 0) or (ry is not None and ry < 0):
        return "Weak"
    return "Mixed"


# ---------- site files ----------
def write_day(d: date, payload):
    jsave(os.path.join(DATA, "days", f"{d.isoformat()}.json"), payload)


def merge_season(kind, rows, key="sym"):
    by_qe = {}
    for r in rows:
        by_qe.setdefault(r["qe"], []).append(r)
    for qe, rs in by_qe.items():
        if qe[5:] not in ("03-31", "06-30", "09-30", "12-31"):
            continue  # event-based filings (e.g. after an allotment) stay in the day file only
        path = os.path.join(DATA, kind, f"{qe}.json")
        cur = jload(path, {"qe": qe, "rows": {}})
        for r in rs:
            cur["rows"][r[key]] = r
        jsave(path, cur)


def rebuild_index():
    days_dir = os.path.join(DATA, "days")
    os.makedirs(days_dir, exist_ok=True)
    files = sorted((f for f in os.listdir(days_dir) if f.endswith(".json")), reverse=True)
    cutoff = (datetime.now(IST).date() - timedelta(days=KEEP_DAYS)).isoformat()
    for f in files:
        if f[:10] < cutoff:
            os.remove(os.path.join(days_dir, f))
    files = [f for f in files if f[:10] >= cutoff]
    seasons = {k: sorted((f[:10] for f in os.listdir(os.path.join(DATA, k)) if f.endswith(".json")), reverse=True)
               if os.path.isdir(os.path.join(DATA, k)) else [] for k in ("results", "holdings")}
    # search index: events (non-Other) + latest results / holdings per symbol
    search = {}
    partial = []
    for f in files:
        day = jload(os.path.join(days_dir, f), {})
        if day.get("refresh") == "mid":
            partial.append(f[:10])
        for a in day.get("announcements", []):
            if a.get("tag") == "Other" or not a.get("sym"):
                continue
            s = search.setdefault(a["sym"], {"n": a.get("name"), "e": []})
            s["e"].append([a.get("time"), a["tag"], a.get("subj"), (a.get("text") or "")[:220], a.get("pdf"), a.get("value_cr")])
    jsave(os.path.join(DATA, "search.json"), search)
    state = jload(os.path.join(CACHE, "state.json"), {})
    jsave(os.path.join(DATA, "index.json"), {
        "updated": datetime.now(IST).isoformat(timespec="minutes"),
        "partial": partial,
        "last_refresh": state.get("last_refresh"),
        "dates": [f[:10] for f in files],
        "results_qe": seasons["results"], "holdings_qe": seasons["holdings"],
    })


def collect_day(c: Collector, d: date, with_deals=True, refresh=None):
    out = {"date": d.isoformat(), "generated": datetime.now(IST).isoformat(timespec="minutes")}
    if refresh:
        out["refresh"] = refresh
    for name, fn in (("announcements", c.announcements), ("results", c.results),
                     ("holdings", c.holdings), ("deals", c.deals)):
        if fn is None:
            out[name] = []
            continue
        try:
            out[name] = fn(d)
        except Exception as e:
            log.exception("%s failed", name)
            import traceback
            tb = traceback.extract_tb(e.__traceback__)[-1]
            out[name] = []
            out.setdefault("errors", []).append(f"{name}: {type(e).__name__} {e!r} at line {tb.lineno}: {tb.line}")
    out["close_date"] = c.close_date
    write_day(d, out)
    merge_season("results", out["results"])
    merge_season("holdings", out["holdings"])
    return out


def update_market(c: Collector, d: date, flow_days):
    """FII/DII flows and the institutional deal file (once per run, not per day)."""
    try:
        flows.update_flows(c.n, os.path.join(DATA, "flows.json"), flow_days, jload, jsave)
    except Exception:
        log.exception("flows failed")
    try:
        rows = c.deal_rows(d)
        flows.write_inst_deals(os.path.join(DATA, "inst_deals.json"), rows, d, c.shares, c.mcap, jsave)
    except Exception:
        log.exception("inst deals failed")


def run_fund(c: Collector, results_rows, minutes):
    try:
        f = fundamentals.Fund(c, DATA, CACHE, jload, jsave, parse_nse_date)
        f.run([r["sym"] for r in results_rows if r.get("sym")], minutes)
        f.fill_series()
        f.save()
    except Exception:
        log.exception("fundamentals failed")


def send_email(d: date, day, force=False):
    import mailer
    fl = jload(os.path.join(DATA, "flows.json"), {})
    day["flows"] = fl.get(d.isoformat())
    prev = [k for k in sorted(fl) if k < d.isoformat() and fl[k].get("poi")]
    day["flows_prev"] = fl[prev[-1]] if prev else None
    state_path = os.path.join(CACHE, "state.json")
    state = jload(state_path, {"emailed": []})
    if force or d.isoformat() not in state.get("emailed", []):
        if mailer.send(day):
            state = jload(state_path, {"emailed": []})
            state["emailed"] = (state.get("emailed", []) + [d.isoformat()])[-60:]
            jsave(state_path, state)


def auto_refresh(c: Collector, a):
    """Two refreshes a day, decided from the IST clock so a late-starting run does the right job:
         13:00-18:30  'mid'  2 PM refresh of today (partial day) + re-check of yesterday, no email
         18:30-24:00  'eod'  end-of-day refresh of today, then the email
         00:00-13:00  a delayed EOD for YESTERDAY if it hasn't happened yet, otherwise nothing
       Each refresh runs once per day; extra triggers exit straight away."""
    now = datetime.now(IST)
    today, h = now.date(), now.hour + now.minute / 60
    if h < 13:
        d, mode = today - timedelta(days=1), "eod"
    elif h < 18.5:
        d, mode = today, "mid"
    else:
        d, mode = today, "eod"
    state_path = os.path.join(CACHE, "state.json")
    state = jload(state_path, {})
    done = state.get("refreshes", [])
    key = f"{d.isoformat()}:{mode}"
    if key in done and not getattr(a, "again", False):
        log.info("%s refresh for %s already done; nothing to do", mode, d)
        return
    log.info("=== %s refresh for %s", mode, d)
    c.load_close(d)
    if mode == "mid":
        y = d - timedelta(days=1)
        if os.path.exists(os.path.join(DATA, "days", f"{y.isoformat()}.json")):
            collect_day(c, y, refresh=jload(os.path.join(DATA, "days", f"{y.isoformat()}.json"), {}).get("refresh"))
    day = collect_day(c, d, refresh=mode)
    update_market(c, d, [d - timedelta(days=i) for i in range(7)])
    if "run_fund" in globals():
        c.budget = Budget(a.fund_minutes + 5)
        run_fund(c, day.get("results") or [], a.fund_minutes)
    state = jload(state_path, {})
    state["refreshes"] = (state.get("refreshes", []) + [key])[-60:]
    state["last_refresh"] = {"date": d.isoformat(), "mode": mode, "at": datetime.now(IST).isoformat(timespec="minutes")}
    jsave(state_path, state)
    rebuild_index()
    if mode == "eod":
        send_email(d, day)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--backfill", nargs=2, metavar=("FROM", "TO"))
    ap.add_argument("--email", action="store_true")
    ap.add_argument("--again", action="store_true", help="with --auto: refresh even if this refresh already ran today")
    ap.add_argument("--auto", action="store_true",
                    help="scheduled refresh: 2 PM (partial, no email) or EOD (full, email) decided from the IST clock")
    ap.add_argument("--force-email", action="store_true")
    ap.add_argument("--budget", type=float, default=40, help="minutes for slow enrichment")
    ap.add_argument("--market-only", action="store_true", help="only refresh FII/DII flows and deal history")
    ap.add_argument("--flow-days", type=int, default=7, help="days of derivatives data to (re)check")
    ap.add_argument("--fund-minutes", type=float, default=30, help="minutes for filling stock fundamentals")
    ap.add_argument("--fund-only", action="store_true", help="only fill stock fundamentals (and prices)")
    ap.add_argument("--series-only", action="store_true", help="only add quarter series to stored fundamentals (no downloads)")
    ap.add_argument("--fund-probe", help="comma-separated symbols: parse their latest filing and print it (testing)")
    a = ap.parse_args()

    c = Collector(budget_min=a.budget)
    today = datetime.now(IST).date()
    if a.market_only:
        d = date.fromisoformat(a.date) if a.date else today
        c.load_close(d)
        update_market(c, d, [d - timedelta(days=i) for i in range(a.flow_days)])
        for k in range(flows.DEAL_DAYS):  # refresh the deals in day files too
            dd = d - timedelta(days=k)
            p = os.path.join(DATA, "days", f"{dd.isoformat()}.json")
            if os.path.exists(p):
                day = jload(p, None)
                if day is not None:
                    day["deals"] = c.deals(dd)
                    jsave(p, day)
        rebuild_index()
        return
    if a.fund_probe:
        import json as _json
        c.load_close(today)
        f = fundamentals.Fund(c, DATA, CACHE, jload, jsave, parse_nse_date)
        for sym in a.fund_probe.split(","):
            f.rows.pop(sym, None)
            cache_path = os.path.join(CACHE, "fin", f"{sym}.json")
            cache = jload(cache_path, {})
            for k in list(cache):
                if cache[k] and cache[k].get("_v") == xbrl.FIN_VERSION:
                    cache.pop(k)
            jsave(cache_path, cache)
            try:
                f.refresh(sym, force=True)
            except Exception as e:
                print(f"::notice title={sym} error::{type(e).__name__}: {e}"[:900])
            r = f.rows.get(sym) or {}
            print(f"::notice title={sym}::state {f.state.get(sym)} " + _json.dumps(r)[:1700])
        return
    if a.series_only:
        f = fundamentals.Fund(c, DATA, CACHE, jload, jsave, parse_nse_date)
        f.fill_series()
        f.save()
        return
    if a.fund_only:
        d = date.fromisoformat(a.date) if a.date else today
        c.budget = Budget(a.fund_minutes + 5)
        c.load_close(d)
        run_fund(c, [], a.fund_minutes)
        rebuild_index()
        return
    if a.backfill:
        d0, d1 = date.fromisoformat(a.backfill[0]), date.fromisoformat(a.backfill[1])
        c.budget = Budget(a.budget)
        c.load_close(d1)
        d = d1
        while d >= d0:  # newest first so the important days finish first
            log.info("=== backfill %s", d)
            collect_day(c, d)
            rebuild_index()
            d -= timedelta(days=1)
        update_market(c, d1, [d1 - timedelta(days=i) for i in range((d1 - d0).days + 1)])
        return
    if a.auto:
        return auto_refresh(c, a)
    d = date.fromisoformat(a.date) if a.date else today
    c.load_close(d)
    day = collect_day(c, d)
    update_market(c, d, [d - timedelta(days=i) for i in range(7)])
    c.budget = Budget(a.fund_minutes + 5)
    run_fund(c, day.get("results") or [], a.fund_minutes)
    rebuild_index()
    if a.email and not a.force_email and datetime.now(IST).hour < 19:
        log.info("before 7 PM IST: collected, email left for a later run")
        a.email = False
    if a.email or a.force_email:
        import mailer
        fl = jload(os.path.join(DATA, "flows.json"), {})
        day["flows"] = fl.get(d.isoformat())
        prev = [k for k in sorted(fl) if k < d.isoformat() and fl[k].get("poi")]
        day["flows_prev"] = fl[prev[-1]] if prev else None
        state_path = os.path.join(CACHE, "state.json")
        state = jload(state_path, {"emailed": []})
        if a.force_email or d.isoformat() not in state["emailed"]:
            if mailer.send(day):
                state["emailed"] = (state["emailed"] + [d.isoformat()])[-60:]
                jsave(state_path, state)


if __name__ == "__main__":
    main()
