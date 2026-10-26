"""Daily email digest via Gmail SMTP (app password)."""
import html, logging, os, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date

log = logging.getLogger("mailer")
SITE = os.environ.get("SITE_URL", "https://vs916491-maker.github.io/NSE-fundamentals-desk/")

GREEN, RED, GREY = "#0a7d38", "#c0392b", "#666"


def e(x):
    return html.escape(str(x if x is not None else ""))


def pct(v):
    if v is None:
        return '<span style="color:#999">–</span>'
    c = GREEN if v >= 0 else RED
    return f'<span style="color:{c}">{v:+.0f}%</span>'


def cr(v):
    if v is None:
        return "–"
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}"


def table(head, rows):
    th = "".join(f'<th style="text-align:left;padding:4px 8px;border-bottom:1px solid #ddd;font-size:12px;color:{GREY}">{h}</th>' for h in head)
    trs = "".join("<tr>" + "".join(f'<td style="padding:4px 8px;border-bottom:1px solid #f0f0f0;font-size:13px">{c}</td>' for c in r) + "</tr>" for r in rows)
    return f'<table style="border-collapse:collapse;width:100%">{"<tr>" + th + "</tr>"}{trs}</table>'


def section(title, body):
    return f'<h3 style="margin:22px 0 6px;font-size:16px">{title}</h3>{body}'


def flows_block(day):
    f = day.get("flows") or {}
    prev = day.get("flows_prev") or {}
    cash, fo, poi = f.get("cash") or {}, f.get("fo") or {}, f.get("poi") or {}
    if not (cash or fo or poi):
        return f'<p style="color:{GREY};font-size:13px">FII/DII figures for today were not published yet at collection time.</p>'
    def net(v):
        if v is None:
            return "–"
        return f'<b style="color:{GREEN if v >= 0 else RED}">{v:+,.0f}</b>'
    rows = []
    if cash:
        rows.append(["Cash market (stocks)", net((cash.get("fii") or {}).get("net")), net((cash.get("dii") or {}).get("net"))])
    if fo.get("idx_fut"):
        rows.append(["Index futures", net(fo["idx_fut"].get("net")), "–"])
    if fo.get("idx_opt"):
        rows.append(["Index options", net(fo["idx_opt"].get("net")), "–"])
    if fo.get("stk_fut"):
        rows.append(["Stock futures", net(fo["stk_fut"].get("net")), "–"])
    html_ = table(["Net buy / sell, ₹ cr", "FII", "DII"], rows) if rows else ""
    fii = poi.get("FII")
    if fii and fii.get("fi_l") is not None:
        l, s_ = fii["fi_l"], fii["fi_s"]
        lp = l / (l + s_) * 100 if (l + s_) else None
        pf = (prev.get("poi") or {}).get("FII")
        chg = ""
        if pf and pf.get("fi_l") is not None and (pf["fi_l"] + pf["fi_s"]):
            d = lp - pf["fi_l"] / (pf["fi_l"] + pf["fi_s"]) * 100
            chg = f' (<span style="color:{GREEN if d >= 0 else RED}">{d:+.1f} pp</span> vs previous day)'
        html_ += (f'<p style="margin:8px 0 0;font-size:13px">FII index futures positions: {l:,.0f} long / {s_:,.0f} short contracts '
                  f'→ <b>{lp:.0f}% long</b>{chg}</p>')
    return section("🌐 FII / DII activity", html_)


def build(day):
    d = day["date"]
    ann = day.get("announcements", [])
    res = day.get("results", [])
    hold = day.get("holdings", [])
    deals = day.get("deals", [])
    by = lambda t: [a for a in ann if a["tag"] == t]
    parts = []

    big = [r for r in res if (r.get("mcap") or 0) >= 500 or (r.get("mcap") is None and (r.get("rev") or 0) >= 100)]
    good = sorted([r for r in big if r.get("verdict") in ("Strong", "Turnaround")],
                  key=lambda r: (r.get("verdict") != "Strong", -(r.get("pat_yoy") or 0)))[:10]
    bad = sorted([r for r in big if r.get("verdict") in ("Weak", "Loss")], key=lambda r: (r.get("pat_yoy") or 0))[:5]

    def rrow(r):
        return [f'<b>{e(r["sym"])}</b>', cr(r.get("mcap")), f'{cr(r.get("rev"))} {pct(r.get("rev_yoy"))}',
                f'{cr(r.get("pat"))} {pct(r.get("pat_yoy"))}', e(r.get("verdict") or "")]
    head = ["Stock", "MCap ₹cr", "Revenue ₹cr (YoY)", "PAT ₹cr (YoY)", ""]
    if res:
        body = f'<p style="margin:0 0 6px;color:{GREY};font-size:13px">{len(res)} companies reported. Shown: market cap ≥ ₹500 cr.</p>'
        if good:
            body += "<p style='margin:8px 0 4px'><b>Strongest</b></p>" + table(head, [rrow(r) for r in good])
        if bad:
            body += "<p style='margin:12px 0 4px'><b>Weakest</b></p>" + table(head, [rrow(r) for r in bad])
        parts.append(section(f"📊 Results ({len(res)})", body))

    orders = sorted(by("Order"), key=lambda a: -(a.get("pct_mcap") or 0) * 1000 - (a.get("value_cr") or 0))
    if orders:
        rows = [[f'<b>{e(a["sym"])}</b>', cr(a.get("value_cr")) if a.get("value_cr") else e(a.get("value_raw") or "–"),
                 f'{a["pct_mcap"]:.1f}%' if a.get("pct_mcap") else "–", e((a.get("text") or "")[:110])] for a in orders[:15]]
        parts.append(section(f"🟢 Orders ({len(orders)})", table(["Stock", "Value ₹cr", "% of MCap", "Detail"], rows)))

    for tag, icon, title in (("Penalty", "🔴", "Penalties / regulatory actions"), ("Buyback", "🔵", "Buybacks"),
                             ("RedFlag", "⚠️", "Red flags")):
        items = by(tag)
        if items:
            rows = [[f'<b>{e(a["sym"])}</b>', e(a.get("subj")), e((a.get("text") or "")[:140])] for a in items[:12]]
            parts.append(section(f"{icon} {title} ({len(items)})", table(["Stock", "Category", "Detail"], rows)))

    ratings = [a for a in by("Rating") if a.get("dir")]
    if ratings:
        rows = [[f'<b>{e(a["sym"])}</b>', f'<span style="color:{GREEN if a["dir"] == "up" else RED}">{"Upgrade" if a["dir"] == "up" else "Downgrade"}</span>',
                 e((a.get("text") or "")[:140])] for a in ratings[:10]]
        parts.append(section(f"⭐ Rating changes ({len(ratings)})", table(["Stock", "Change", "Detail"], rows)))

    movers = []
    for h in hold:
        for k, lab in (("fii", "FII"), ("dii", "DII"), ("promoter", "Promoter")):
            ch = h.get(k + "_chg")
            if ch is not None and abs(ch) >= 1:
                movers.append((abs(ch), h, lab, k, ch))
    movers.sort(key=lambda x: -x[0])
    if movers:
        rows = [[f'<b>{e(h["sym"])}</b>', lab, f'{h[k]:.2f}%', f'<span style="color:{GREEN if ch > 0 else RED}">{ch:+.2f} pp</span>']
                for _, h, lab, k, ch in movers[:12]]
        parts.append(section(f"🏦 Holding changes ≥ 1 pp ({len(hold)} filings today)", table(["Stock", "Holder", "Now", "Change QoQ"], rows)))

    inst = [x for x in deals if x.get("inst") and x["value_cr"] >= 5]
    if inst:
        rows = [[f'<b>{e(x["sym"])}</b>', e(x["client"][:40]), e(x.get("itype") or ""),
                 f'<span style="color:{GREEN if x["side"] == "BUY" else RED}">{e(x["side"])}</span>',
                 cr(x["value_cr"])] for x in inst[:12]]
        parts.append(section(f"💼 Institutional bulk/block deals ({len(inst)})", table(["Stock", "Client", "Type", "Side", "₹cr"], rows)))

    parts.insert(0, flows_block(day))
    if len(parts) == 1:
        parts.append("<p>No tagged events today.</p>")

    counts = " · ".join(f"{k}: {len(by(k))}" for k in ("Order", "Penalty", "Buyback", "RedFlag"))
    nice = date.fromisoformat(d).strftime("%a %d %b %Y")
    errors = "".join(f'<p style="color:{RED};font-size:12px">Data issue: {e(x)}</p>' for x in day.get("errors", []))
    return f"""<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:720px;margin:auto;color:#222">
<h2 style="margin:0 0 4px">NSE Fundamentals — {nice}</h2>
<p style="margin:0;color:{GREY};font-size:13px">{len(res)} results · {counts}</p>
{errors}{''.join(parts)}
<p style="margin:28px 0 8px"><a href="{SITE}" style="background:#1f4fd1;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none">Open the full desk</a></p>
<p style="color:#999;font-size:11px">Source: NSE corporate filings. Automated tagging can misclassify; check the filing before acting. Not investment advice.</p>
</div>"""


def send(day) -> bool:
    user = os.environ.get("GMAIL_USER")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("EMAIL_TO") or user
    if not user or not pw:
        log.warning("GMAIL_USER / GMAIL_APP_PASSWORD not set; skipping email")
        return False
    msg = MIMEMultipart("alternative")
    nice = date.fromisoformat(day["date"]).strftime("%d %b")
    res = day.get("results", [])
    n_orders = sum(1 for a in day.get("announcements", []) if a["tag"] == "Order")
    msg["Subject"] = f"NSE Fundamentals {nice}: {len(res)} results, {n_orders} orders"
    msg["From"] = f"Fundamentals Desk <{user}>"
    msg["To"] = to
    msg.attach(MIMEText(build(day), "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
            s.login(user, pw.replace(" ", ""))
            s.sendmail(user, [to], msg.as_string())
        log.info("email sent to %s", to)
        return True
    except Exception as ex:
        log.error("email failed: %s", ex)
        return False
