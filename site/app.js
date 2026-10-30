"use strict";
const $ = (s) => document.querySelector(s);
const TAGS = [
  ["Results", "Results"], ["Order", "Orders"], ["Penalty", "Penalties"], ["Buyback", "Buybacks"],
  ["Rating", "Ratings"], ["RedFlag", "Red flags"], ["Management", "Management"], ["Other", "Routine"],
];
const S = {
  index: null, date: null, days: {}, seasons: { results: {}, holdings: {} }, search: null,
  tag: null, resScope: "day", holdScope: "day", sort: {},
  flows: null, inst: null, addWin: 30, addType: "", fiiRange: 130,
};
const TYPE_LABEL = { FII: "FII", DII: "DII", Fund: "AIF/PMS" };
const badge = (t) => t ? `<span class="badge b-${t}">${TYPE_LABEL[t] || t}</span>` : "";

// ---------- utils ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = (v, d = 0) => v == null ? "–" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const cr = (v) => v == null ? "–" : inr(v, Math.abs(v) >= 100 ? 0 : 1);
const pct = (v) => v == null ? '<span class="dim">–</span>' : `<span class="${v >= 0 ? "up" : "down"}">${v > 0 ? "+" : ""}${inr(v, Math.abs(v) >= 100 ? 0 : 1)}%</span>`;
const pp = (v) => v == null ? '<span class="dim">–</span>' : `<span class="${v > 0 ? "up" : v < 0 ? "down" : "dim"}">${v > 0 ? "+" : ""}${v.toFixed(2)}</span>`;
const qLabel = (qe) => {
  const d = new Date(qe + "T00:00:00"); const m = d.getMonth() + 1; const y = d.getFullYear();
  const q = { 6: 1, 9: 2, 12: 3, 3: 4 }[m]; const fy = m >= 4 ? y + 1 : y;
  return `Q${q} FY${String(fy).slice(2)}`;
};
const niceDate = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const timeOf = (s) => { const m = String(s || "").match(/(\d{2}:\d{2})/); return m ? m[1] : ""; };
async function getJSON(path) {
  const r = await fetch(path + (path.includes("?") ? "" : `?v=${S.index?.updated || Date.now()}`));
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
/* TradingView daily chart for an NSE symbol (opens in a new tab, in your saved TradingView layout) */
const tvHref = (s) => `https://www.tradingview.com/chart/?symbol=${encodeURIComponent("NSE:" + String(s).toUpperCase().replace(/[&-]/g, "_"))}&interval=D`;
const CHART_SVG = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><line x1="4" y1="2" x2="4" y2="14" stroke="currentColor" stroke-width="1.4"/><rect x="2.2" y="5" width="3.6" height="6" rx=".6" fill="currentColor"/><line x1="11" y1="1.5" x2="11" y2="12.5" stroke="currentColor" stroke-width="1.4"/><rect x="9.2" y="3.5" width="3.6" height="6" rx=".6" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>';
const chartLink = (s) => s ? `<a class="chart-link" href="${tvHref(s)}" target="_blank" rel="noopener" title="Open ${esc(s)} chart on TradingView" aria-label="Open ${esc(s)} chart on TradingView">${CHART_SVG}</a>` : "";
const symLink = (s) => `<span class="sym" data-sym="${esc(s)}">${esc(s)}</span>${chartLink(s)}`;

// ---------- theme ----------
(function theme() {
  let t = null; try { t = localStorage.getItem("theme"); } catch (e) {}
  if (t) document.documentElement.dataset.theme = t;
  $("#themeBtn").onclick = () => {
    const dark = matchMedia("(prefers-color-scheme: dark)").matches;
    const cur = document.documentElement.dataset.theme || (dark ? "dark" : "light");
    const nxt = cur === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = nxt;
    try { localStorage.setItem("theme", nxt); } catch (e) {}
  };
})();

// ---------- data ----------
async function loadDay(d) {
  if (!S.days[d]) S.days[d] = await getJSON(`data/days/${d}.json`);
  return S.days[d];
}
async function loadSeason(kind, qe) {
  if (!S.seasons[kind][qe]) S.seasons[kind][qe] = await getJSON(`data/${kind}/${qe}.json`);
  return S.seasons[kind][qe];
}

async function loadFlows() {
  if (!S.flows) S.flows = await getJSON("data/flows.json").catch(() => ({}));
  return S.flows;
}
async function loadInst() {
  if (!S.inst) S.inst = await getJSON("data/inst_deals.json").catch(() => null);
  return S.inst;
}

// ---------- FII / DII activity ----------
const netv = (v) => v == null ? '<span class="dim">–</span>' : `<span class="${v >= 0 ? "up" : "down"}">${v > 0 ? "+" : ""}${inr(v)}</span>`;
const longPct = (o, l, s) => o && o[l] != null && (o[l] + o[s]) ? o[l] / (o[l] + o[s]) * 100 : null;
const shortDay = (x) => new Date(x + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
const VERDICT = {
  "Bullish": ["vb2", "▲▲"], "Mildly bullish": ["vb1", "▲"], "Neutral": ["vn", "●"],
  "Mildly bearish": ["vr1", "▼"], "Bearish": ["vr2", "▼▼"],
};
const vTag = (lab) => lab ? `<span class="vtag ${VERDICT[lab][0]}">${VERDICT[lab][1]} ${lab}</span>` : '<span class="dim">–</span>';

function flowDay(fl) {
  const dates = Object.keys(fl).sort();
  const upto = dates.filter((d) => d <= (S.date || dates[dates.length - 1]));
  return { dates, d: upto[upto.length - 1] };
}

function flowCards(fl, dates, d) {
  const f = fl[d] || {};
  const prevD = dates.filter((x) => x < d && fl[x].poi).pop();
  const pf = prevD ? fl[prevD] : {};
  const cash = f.cash || {}, fo = f.fo || {}, poi = f.poi || {};
  const fii = poi.FII, pfii = (pf.poi || {}).FII;
  const card = (title, body) => `<div class="fcard"><h4>${title}</h4>${body}</div>`;
  const lsBlock = (o, po, l, s, label) => {
    const p = longPct(o, l, s); if (p == null) return "";
    const pp_ = longPct(po, l, s);
    const ch = pp_ == null ? "" : ` · <span class="${p - pp_ >= 0 ? "up" : "down"}">${p - pp_ >= 0 ? "+" : ""}${(p - pp_).toFixed(1)} pp</span>`;
    return `<div class="lsbar" title="${inr(o[l])} long vs ${inr(o[s])} short"><span style="width:${p.toFixed(1)}%"></span></div>
      <div class="lsnote">${label}: <b>${p.toFixed(0)}% long</b> (${inr(o[l])} L / ${inr(o[s])} S)${ch}</div>`;
  };
  const cards = [];
  if (cash.fii || cash.dii) cards.push(card("Cash market · net ₹ cr",
    `<div class="frow"><span class="who">FII</span><span class="big">${netv(cash.fii?.net)}</span></div>
     <div class="frow"><span class="small">buy ${inr(cash.fii?.buy)} · sell ${inr(cash.fii?.sell)}</span></div>
     <div class="frow"><span class="who">DII</span><span class="big">${netv(cash.dii?.net)}</span></div>
     <div class="frow"><span class="small">buy ${inr(cash.dii?.buy)} · sell ${inr(cash.dii?.sell)}</span></div>`));
  if (fo.idx_fut || fii) cards.push(card("FII index futures",
    `<div class="frow"><span class="who">Net ₹ cr</span><span class="big">${netv(fo.idx_fut?.net)}</span></div>
     ${lsBlock(fii, pfii, "fi_l", "fi_s", "Positions")}`));
  if (fo.idx_opt || fii) {
    const nc = fii && fii.ic_l != null ? fii.ic_l - fii.ic_s : null, np = fii && fii.ip_l != null ? fii.ip_l - fii.ip_s : null;
    cards.push(card("FII index options",
      `<div class="frow"><span class="who">Net ₹ cr</span><span class="big">${netv(fo.idx_opt?.net)}</span></div>
       <div class="frow"><span class="small">Calls long − short</span><span class="small">${netv(nc)}</span></div>
       <div class="frow"><span class="small">Puts long − short</span><span class="small">${netv(np)}</span></div>`));
  }
  if (fo.stk_fut || fii) cards.push(card("FII stock futures",
    `<div class="frow"><span class="who">Net ₹ cr</span><span class="big">${netv(fo.stk_fut?.net)}</span></div>
     ${lsBlock(fii, pfii, "fs_l", "fs_s", "Positions")}`));
  const who = ["FII", "DII", "Pro", "Client"].filter((k) => poi[k]).map((k) => {
    const p = longPct(poi[k], "fi_l", "fi_s"), q = longPct((pf.poi || {})[k], "fi_l", "fi_s");
    return `<tr><td class="l">${k === "Client" ? "Client (retail)" : k === "Pro" ? "Pro (brokers' own)" : k}</td><td>${inr(poi[k].fi_l)}</td><td>${inr(poi[k].fi_s)}</td><td>${p == null ? "–" : p.toFixed(1) + "%"}</td>
      <td>${p == null || q == null ? "–" : pp(+(p - q).toFixed(2))}</td></tr>`; }).join("");
  return { cards: cards.join(""), who };
}

// Today: one compact line
async function renderFlowsCompact() {
  const box = $("#flows");
  const fl = await loadFlows();
  const { d } = flowDay(fl);
  if (!d) { box.innerHTML = ""; return; }
  const f = fl[d], v = f.view || {}, fii = (f.poi || {}).FII, lp = longPct(fii, "fi_l", "fi_s");
  const bits = [];
  if (f.cash) bits.push(`FII cash <b>${netv(f.cash.fii?.net)}</b>`, `DII cash <b>${netv(f.cash.dii?.net)}</b>`);
  if (lp != null) bits.push(`FII index futures <b>${lp.toFixed(0)}% long</b>`);
  if (v.short) bits.push(`Short term ${vTag(v.short.label)}`);
  if (v.swing) bits.push(`Swing ${vTag(v.swing.label)}`);
  box.innerHTML = `<a class="flowline" href="#fii"><span class="fl-title">FII / DII · ${shortDay(d)}</span>${bits.map((b) => `<span>${b}</span>`).join("")}<span class="fl-more">Details →</span></a>`;
}

// tiny SVG chart: one y-axis, crosshair tooltip
const compact = (v) => Math.abs(v) >= 1e7 ? inr(v / 1e7, 1) + " Cr" : Math.abs(v) >= 1e5 ? inr(v / 1e5, Math.abs(v) >= 1e6 ? 0 : 1) + " L" : inr(v);
function svgChart(el, { dates, series, kind = "line", fmt = (v) => inr(v), zero = false, yMin = null, yMax = null }) {
  const W = Math.max(280, el.clientWidth || 560), H = 190, m = { l: 52, r: 14, t: 10, b: 24 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b, n = dates.length;
  let vals = series.flatMap((s) => s.values.filter((v) => v != null));
  if (!vals.length) { el.innerHTML = '<div class="empty" style="padding:40px 0">No data for this range yet.</div>'; return; }
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (zero || kind === "bar") { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (yMin != null) lo = Math.min(lo, yMin); if (yMax != null) hi = Math.max(hi, yMax);
  if (hi === lo) { hi += 1; lo -= 1; }
  const span = hi - lo, step0 = span / 4, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= step0);
  lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
  const y = (v) => m.t + ih - (v - lo) / (hi - lo) * ih;
  const bw = iw / n, x = (i) => m.l + bw * i + bw / 2;
  let g = "";
  for (let t = lo; t <= hi + step / 2; t += step) {
    g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" class="${Math.abs(t) < step / 1e6 && lo < 0 ? "zl" : "gl"}"/>`;
    g += `<text x="${m.l - 6}" y="${y(t) + 4}" class="yt">${fmt(Math.abs(t) < step / 1e6 ? 0 : t)}</text>`;
  }
  const ticks = Math.max(2, Math.min(6, n, Math.floor(iw / 75) + 1));
  for (let k = 0; k < ticks; k++) {
    const i = Math.round(k * (n - 1) / Math.max(1, ticks - 1));
    g += `<text x="${x(i)}" y="${H - 6}" class="xt" text-anchor="${k === 0 ? "start" : k === ticks - 1 ? "end" : "middle"}">${shortDay(dates[i])}</text>`;
  }
  let marks = "";
  series.forEach((s, si) => {
    if (kind === "bar") {
      const w = Math.max(1, bw - 2);
      s.values.forEach((v, i) => {
        if (v == null) return;
        const y0 = y(0), y1 = y(v), h = Math.max(1, Math.abs(y1 - y0));
        marks += `<rect x="${x(i) - w / 2}" y="${Math.min(y0, y1)}" width="${w}" height="${h}" rx="${Math.min(2, w / 2)}" class="${v >= 0 ? "bu" : "bd"}"/>`;
      });
    } else {
      let d = "", pen = false;
      s.values.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; });
      marks += `<path d="${d}" class="ln" style="stroke:var(${s.color || "--c1"})"/>`;
      const li = s.values.map((v, i) => v == null ? -1 : i).filter((i) => i >= 0).pop();
      if (li != null && li >= 0) marks += `<circle cx="${x(li)}" cy="${y(s.values[li])}" r="3.5" style="fill:var(${s.color || "--c1"})" class="endpt"/>`;
    }
  });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">${g}${marks}
    <line class="xh" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" style="display:none"/>
    <rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent" class="hit"/></svg><div class="tip" hidden></div>`;
  const svg = el.querySelector("svg"), xh = svg.querySelector(".xh"), tip = el.querySelector(".tip");
  const show = (cx) => {
    const r = svg.getBoundingClientRect(), px = (cx - r.left) * (W / r.width);
    const i = Math.max(0, Math.min(n - 1, Math.floor((px - m.l) / bw)));
    xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.style.display = "";
    tip.innerHTML = `<div class="tdate">${niceDate(dates[i])}</div>` + series.map((s) =>
      `<div class="trow">${series.length > 1 || kind === "line" ? `<i style="background:var(${s.color || "--c1"})"></i>` : ""}<b>${s.values[i] == null ? "–" : fmt(s.values[i])}</b>${s.name ? `<span>${esc(s.name)}</span>` : ""}</div>`).join("");
    tip.hidden = false;
    const left = x(i) / W * r.width;
    tip.style.left = Math.min(Math.max(0, left + 12), r.width - tip.offsetWidth - 4) + "px";
  };
  const hit = svg.querySelector(".hit");
  hit.addEventListener("pointermove", (e) => show(e.clientX));
  hit.addEventListener("pointerdown", (e) => show(e.clientX));
  hit.addEventListener("pointerleave", () => { xh.style.display = "none"; tip.hidden = true; });
}

const RANGES = [["1M", 22], ["3M", 66], ["6M", 130]];
async function renderFii() {
  const fl = await loadFlows();
  const { dates, d } = flowDay(fl);
  if (!d) { $("#fiiTop").innerHTML = '<div class="empty">No FII/DII data yet.</div>'; return; }
  const f = fl[d], v = f.view || {}, ctx = v.ctx || {};
  $("#fiiRange").innerHTML = RANGES.map(([l, k]) => `<button data-k="${k}" class="${S.fiiRange === k ? "on" : ""}">${l}</button>`).join("");
  $("#fiiRange").querySelectorAll("button").forEach((b) => b.onclick = () => { S.fiiRange = +b.dataset.k; render(); });
  $("#fiiDate").textContent = niceDate(d) + (d !== S.date ? " (latest available)" : "");

  const vcard = (title, h) => {
    if (!h) return `<div class="vcard"><h4>${title}</h4><div class="dim">Not enough history yet.</div></div>`;
    const pts = (p) => `<span class="pts ${p > 0 ? "up" : p < 0 ? "down" : "dim"}">${p > 0 ? "+" : ""}${p}</span>`;
    return `<div class="vcard"><h4>${title}</h4><div class="vhead">${vTag(h.label)}<span class="vscore">score ${h.score > 0 ? "+" : ""}${h.score}</span></div>
      <ul class="vparts">${h.parts.map((c) => `<li>${pts(c.pts)}<div><b>${esc(c.name)}</b> ${esc(c.text)}</div></li>`).join("")}</ul></div>`;
  };
  const posCard = `<div class="vcard"><h4>Where FIIs stand (index futures)</h4>
    <div class="vhead"><span class="vtag vn">${esc(ctx.positioning || "–")}</span><span class="vscore">${ctx.long_pct == null ? "" : ctx.long_pct + "% long"}</span></div>
    ${ctx.pctile != null ? `<p class="small-p">More bearish than on ${100 - ctx.pctile}% of days in the last 6 months.</p>` : ""}
    ${ctx.note ? `<p class="small-p">${esc(ctx.note)}</p>` : ""}
    <p class="small-p dim">The verdicts show which way FIIs are <i>moving</i>; this shows where they <i>stand</i>. Both matter: heavy shorts that start covering are a classic bullish setup.</p></div>`;
  $("#fiiTop").innerHTML = `<div class="vgrid">${vcard("Short term · next 1–3 days", v.short)}${vcard("Swing · next 2–4 weeks", v.swing)}${posCard}</div>`;

  const { cards, who } = flowCards(fl, dates, d);
  $("#fiiCards").innerHTML = `<div class="flowgrid">${cards}</div>`;

  // charts
  const keys = dates.filter((x) => x <= d && (fl[x].poi || fl[x].fo || fl[x].cash)).slice(-S.fiiRange);
  const pick = (fn) => keys.map((k) => { try { const r = fn(fl[k]); return r == null || isNaN(r) ? null : r; } catch (e) { return null; } });
  const F = (g) => (g.poi || {}).FII || {};
  const charts = [
    ["FII sentiment score", "Above 0 = FII activity leaning bullish. Swing ≥ +3 is a bullish read, ≤ −3 bearish.", { kind: "line", zero: true, yMin: -4, yMax: 4,
      fmt: (v) => (v > 0 ? "+" : "") + inr(v, Math.abs(v) < 10 && v % 1 ? 1 : 0),
      series: [{ name: "Swing", color: "--c1", values: pick((g) => g.view?.swing?.score) }, { name: "Short term", color: "--c2", values: pick((g) => g.view?.short?.score) }] }],
    ["NIFTY 50", "Closing level, for context.", { kind: "line", series: [{ name: "NIFTY 50", values: pick((g) => g.idx?.nifty) }] }],
    ["FII index futures · % of positions long", "Rising = short covering or fresh longs (bullish). Falling = fresh shorts (bearish).", { kind: "line",
      fmt: (v) => inr(v, 1) + "%", series: [{ name: "Long %", values: pick((g) => longPct(F(g), "fi_l", "fi_s")) }] }],
    ["FII index futures · net buy / sell, ₹ cr", "Daily buy minus sell value.", { kind: "bar", series: [{ name: "", values: pick((g) => g.fo?.idx_fut?.net) }] }],
    ["FII index options · net position, contracts", "Net calls rising or net puts falling = bullish tilt. L = lakh contracts.", { kind: "line", zero: true, fmt: compact,
      series: [{ name: "Net calls (long − short)", color: "--c1", values: pick((g) => F(g).ic_l - F(g).ic_s) },
               { name: "Net puts (long − short)", color: "--c2", values: pick((g) => F(g).ip_l - F(g).ip_s) }] }],
    ["FII stock futures · % of positions long", "Noisier: many shorts here are cash-futures arbitrage.", { kind: "line",
      fmt: (v) => inr(v, 1) + "%", series: [{ name: "Long %", values: pick((g) => longPct(F(g), "fs_l", "fs_s")) }] }],
    ["FII stock futures · net buy / sell, ₹ cr", "Daily buy minus sell value.", { kind: "bar", series: [{ name: "", values: pick((g) => g.fo?.stk_fut?.net) }] }],
    ["FII cash market · net ₹ cr", "NSE provisional figures; history starts 23 Oct 2026.", { kind: "bar", series: [{ name: "", values: pick((g) => g.cash?.fii?.net) }] }],
    ["DII cash market · net ₹ cr", "NSE provisional figures; history starts 23 Oct 2026.", { kind: "bar", series: [{ name: "", values: pick((g) => g.cash?.dii?.net) }] }],
  ];
  $("#fiiCharts").innerHTML = charts.map(([t, sub, o], i) => `<div class="ccard"><div class="chead"><h4>${t}</h4>
      ${o.series.length > 1 ? `<div class="legend">${o.series.map((s) => `<span><i style="background:var(${s.color})"></i>${esc(s.name)}</span>`).join("")}</div>` : ""}</div>
      <p class="csub">${sub}</p><div class="chart" id="ch${i}"></div></div>`).join("");
  charts.forEach(([, , o], i) => svgChart($("#ch" + i), { dates: keys, ...o }));

  const last = dates.filter((x) => x <= d).slice(-10).reverse();
  const hist = last.map((x) => { const g = fl[x] || {}, gp = (g.poi || {}).FII, lp = longPct(gp, "fi_l", "fi_s");
    return `<tr><td class="l">${new Date(x + "T00:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}</td>
      <td class="l">${vTag(g.view?.short?.label)}</td><td class="l">${vTag(g.view?.swing?.label)}</td>
      <td>${netv(g.cash?.fii?.net)}</td><td>${netv(g.cash?.dii?.net)}</td>
      <td>${netv(g.fo?.idx_fut?.net)}</td><td>${lp == null ? "–" : lp.toFixed(1) + "%"}</td>
      <td>${netv(g.fo?.idx_opt?.net)}</td><td>${netv(g.fo?.stk_fut?.net)}</td><td>${g.idx?.nifty ? inr(g.idx.nifty) : "–"}</td></tr>`; }).join("");
  $("#fiiTables").innerHTML = `<h3>Last 10 sessions</h3><div class="tablewrap"><table class="grid"><thead><tr><th class="l">Day</th><th class="l">Short term</th><th class="l">Swing</th><th>FII cash</th><th>DII cash</th><th>FII idx fut</th><th>Idx fut long</th><th>FII idx opt</th><th>FII stk fut</th><th>NIFTY</th></tr></thead><tbody>${hist}</tbody></table></div>
    ${who ? `<h3>Who is long index futures</h3><div class="tablewrap"><table class="grid"><thead><tr><th class="l">Participant</th><th>Long</th><th>Short</th><th>Long %</th><th>Δ pp vs prev day</th></tr></thead><tbody>${who}</tbody></table></div>` : ""}`;
}
let fiiResize;
window.addEventListener("resize", () => { clearTimeout(fiiResize); fiiResize = setTimeout(() => { if (currentTab() === "fii") render(); }, 200); });

// ---------- FII/DII Adding ----------
const ADD_COLS = [
  { key: "sym", label: "Stock", l: 1, f: (r) => `${symLink(r.sym)}<span class="name">${esc(r.name)}</span>`, sv: (r) => r.sym },
  { key: "mcap", label: "MCap ₹cr", f: (r) => cr(r.mcap) },
  { key: "net", label: "Net ₹cr", f: (r) => netv(r.net), sv: (r) => r.net },
  { key: "buy", label: "Bought ₹cr", f: (r) => cr(r.buy) },
  { key: "sell", label: "Sold ₹cr", f: (r) => r.sell ? cr(r.sell) : '<span class="dim">–</span>' },
  { key: "pct", label: "Net % equity", f: (r) => r.pct == null ? '<span class="dim">–</span>' : `<span class="${r.pct >= 0 ? "up" : "down"}">${r.pct > 0 ? "+" : ""}${r.pct.toFixed(2)}%</span>` },
  { key: "nb", label: "Buyers", f: (r) => r.nb },
  { key: "days", label: "Deal days", f: (r) => r.days },
  { key: "last", label: "Last deal", l: 1, f: (r) => `<span class="dim">${esc(r.last.slice(8, 10) + "-" + r.last.slice(5, 7))}</span>` },
  { key: "who", label: "Institutions", l: 1, f: (r) => `<div class="who-list">${r.who}</div>`, sv: (r) => r.nb },
];
async function renderAdding() {
  const data = await loadInst();
  $("#addWin").innerHTML = [7, 30, 90].map((w) => `<button data-w="${w}" class="${S.addWin === w ? "on" : ""}">${w}D</button>`).join("");
  $("#addType").innerHTML = [["", "All"], ["FII", "FII"], ["DII", "DII"], ["Fund", "AIF/PMS"]]
    .map(([v, l]) => `<button data-t="${v}" class="${S.addType === v ? "on" : ""}">${l}</button>`).join("");
  $("#addWin").querySelectorAll("button").forEach((b) => b.onclick = () => { S.addWin = +b.dataset.w; render(); });
  $("#addType").querySelectorAll("button").forEach((b) => b.onclick = () => { S.addType = b.dataset.t; render(); });
  if (!data) { $("#addTable").innerHTML = '<tbody><tr><td class="empty">No deal history yet.</td></tr></tbody>'; return; }
  const to = new Date(data.to + "T00:00:00");
  const from = new Date(to - (S.addWin - 1) * 864e5).toISOString().slice(0, 10);
  const side = $("#addSide").value, min = +$("#addMin").value, q = $("#addQ").value.trim().toLowerCase();
  const agg = {};
  for (const [dt, kind, sym, client, sd, qty, price, val, type] of data.rows) {
    if (dt < from || (S.addType && type !== S.addType)) continue;
    const a = agg[sym] || (agg[sym] = { sym, name: data.names[sym] || "", buy: 0, sell: 0, nq: 0, buyers: {}, sellers: {}, d: new Set(), last: "", hit: false });
    const sign = sd === "BUY" ? 1 : -1;
    if (sign > 0) { a.buy += val; a.buyers[client] = [(a.buyers[client]?.[0] || 0) + val, type]; }
    else { a.sell += val; a.sellers[client] = [(a.sellers[client]?.[0] || 0) + val, type]; }
    a.nq += sign * qty; a.d.add(dt); if (dt > a.last) a.last = dt;
    if (q && client.toLowerCase().includes(q)) a.hit = true;
  }
  let rows = Object.values(agg).map((a) => {
    const net = +(a.buy - a.sell).toFixed(2), sh = data.shares[a.sym];
    const list = Object.entries(side === "buy" ? a.buyers : a.sellers).sort((x, y) => y[1][0] - x[1][0]);
    const who = list.slice(0, 3).map(([c, [v, t]]) => `${esc(c.length > 34 ? c.slice(0, 33) + "…" : c)}${badge(t)} <span class="dim">₹${cr(v)}</span>`).join("<br>") +
      (list.length > 3 ? `<br><span class="dim">+${list.length - 3} more</span>` : "");
    return { sym: a.sym, name: a.name, mcap: data.mcap[a.sym], buy: +a.buy.toFixed(2), sell: +a.sell.toFixed(2), net,
      pct: sh ? a.nq / sh * 100 : null, nb: Object.keys(a.buyers).length, days: a.d.size, last: a.last, who, hit: a.hit };
  });
  rows = rows.filter((r) => (side === "buy" ? r.net > 0 : r.net < 0) && Math.abs(r.net) >= min &&
    (!q || r.sym.toLowerCase().includes(q) || r.name.toLowerCase().includes(q) || r.hit));
  $("#addNote").innerHTML = `${rows.length} stocks with institutional net ${side === "buy" ? "buying" : "selling"} in bulk/block deals, ${niceDate(from)} to ${niceDate(data.to)}. ` +
    `Only large trades are reported as bulk/block deals (over 0.5% of a company's shares in a day, or ₹10 cr+ block trades), so most institutional buying in large caps never shows up here. ` +
    `Institution type is guessed from the client name; HFT/prop desks are excluded.`;
  if (side === "sell") { const st = S.sort.add; if (!st || st.key === "net") S.sort.add = { key: "net", asc: true }; }
  else if (S.sort.add && S.sort.add.key === "net" && S.sort.add.asc) S.sort.add = { key: "net", asc: false };
  table($("#addTable"), "add", ADD_COLS, rows, ["net", false]);
}

// ---------- sortable table ----------
function table(el, id, cols, rows, defSort) {
  const st = S.sort[id] || (S.sort[id] = { key: defSort[0], asc: defSort[1] });
  const col = cols.find((c) => c.key === st.key) || cols[0];
  const val = col.sv || ((r) => r[col.key]);
  rows = rows.slice().sort((a, b) => {
    let x = val(a), y = val(b);
    if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
    if (typeof x === "string") return st.asc ? x.localeCompare(y) : y.localeCompare(x);
    return st.asc ? x - y : y - x;
  });
  const th = cols.map((c) => `<th data-k="${c.key}" class="${c.l ? "l " : ""}${c.key === st.key ? "sorted" + (st.asc ? " asc" : "") : ""}">${c.label}</th>`).join("");
  const body = rows.length ? rows.map((r) => "<tr>" + cols.map((c) => `<td class="${c.l ? "l" : ""}">${c.f ? c.f(r) : esc(r[c.key] ?? "–")}</td>`).join("") + "</tr>").join("")
    : `<tr><td colspan="${cols.length}" class="empty">Nothing to show for this selection.</td></tr>`;
  el.innerHTML = `<thead><tr>${th}</tr></thead><tbody>${body}</tbody>`;
  el.querySelectorAll("th").forEach((h) => h.onclick = () => {
    const k = h.dataset.k;
    S.sort[id] = st.key === k ? { key: k, asc: !st.asc } : { key: k, asc: false };
    render();
  });
}

// ---------- Today ----------
function renderToday(day) {
  const pn = $("#partialNote");
  if (pn) pn.innerHTML = (S.index.partial || []).includes(S.date)
    ? `<div class="partial">Partial day: filings up to the 2 PM refresh. The full day, results filed after market hours and FII/DII figures arrive with the end-of-day refresh.</div>` : "";
  const ann = day.announcements || [];
  const counts = Object.fromEntries(TAGS.map(([t]) => [t, 0]));
  ann.forEach((a) => counts[a.tag] = (counts[a.tag] || 0) + 1);
  const resCount = (day.results || []).length;
  $("#tiles").innerHTML = TAGS.filter(([t]) => t !== "Other").map(([t, l]) => {
    const n = t === "Results" ? Math.max(resCount, counts[t]) : counts[t];
    return `<button class="tile ${S.tag === t ? "on" : ""}" data-t="${t}" style="--c:var(--t-${t})"><div class="n">${n}</div><div class="l">${l}</div></button>`;
  }).join("");
  $("#tiles").querySelectorAll(".tile").forEach((b) => b.onclick = () => {
    const t = b.dataset.t;
    if (t === "Results" && resCount) { location.hash = "#results"; return; }
    S.tag = S.tag === t ? null : t; render();
  });
  const q = $("#todayQ").value.trim().toLowerCase();
  const showOther = $("#showOther").checked;
  const order = Object.fromEntries(TAGS.map(([t], i) => [t, i]));
  let items = ann.filter((a) => (S.tag ? a.tag === S.tag : (showOther || a.tag !== "Other")))
    .filter((a) => !q || (a.sym || "").toLowerCase().includes(q) || (a.name || "").toLowerCase().includes(q));
  items.sort((a, b) => (order[a.tag] - order[b.tag]) || ((b.pct_mcap || 0) - (a.pct_mcap || 0)) || String(b.time).localeCompare(String(a.time)));
  const label = Object.fromEntries(TAGS);
  $("#feed").innerHTML = items.length ? items.slice(0, 400).map((a) => {
    const chips = [];
    if (a.value_cr) chips.push(`<span class="chip">₹${cr(a.value_cr)} cr</span>`);
    else if (a.value_raw) chips.push(`<span class="chip">${esc(a.value_raw)}</span>`);
    if (a.pct_mcap) chips.push(`<span class="chip ${a.pct_mcap >= 10 ? "hot" : ""}">${a.pct_mcap.toFixed(1)}% of MCap</span>`);
    if (a.mcap) chips.push(`<span class="chip">MCap ₹${cr(a.mcap)} cr</span>`);
    if (a.dir) chips.push(`<span class="chip" style="color:var(--${a.dir === "up" ? "up" : "down"})">${a.dir === "up" ? "Upgrade" : "Downgrade"}</span>`);
    return `<article class="card" style="--c:var(--t-${a.tag})">
      <div class="head"><span class="pill">${label[a.tag] || a.tag}</span>${symLink(a.sym)}<span class="co">${esc(a.name)}</span><span class="time">${timeOf(a.time)}</span></div>
      <div class="subj">${esc(a.subj)}</div>
      ${a.text ? `<div class="txt">${esc(a.text)}</div>` : ""}
      <div class="chips">${chips.join("")}${a.pdf ? `<a class="pdf" href="${esc(a.pdf)}" target="_blank" rel="noopener">Filing ↗</a>` : ""}</div>
    </article>`;
  }).join("") : `<div class="empty">No ${S.tag ? label[S.tag].toLowerCase() : "tagged filings"} on this day${showOther ? "" : ". Tick “Show routine filings” to see everything"}.</div>`;
}

// ---------- Results ----------
const RES_COLS = [
  { key: "sym", label: "Stock", l: 1, f: (r) => `${symLink(r.sym)}<span class="name">${esc(r.name)}</span>`, sv: (r) => r.sym },
  { key: "mcap", label: "MCap ₹cr", f: (r) => cr(r.mcap) },
  { key: "rev", label: "Revenue ₹cr", f: (r) => cr(r.rev) },
  { key: "rev_yoy", label: "Rev YoY", f: (r) => pct(r.rev_yoy) },
  { key: "rev_qoq", label: "Rev QoQ", f: (r) => pct(r.rev_qoq) },
  { key: "pat", label: "PAT ₹cr", f: (r) => cr(r.pat) },
  { key: "pat_yoy", label: "PAT YoY", f: (r) => pct(r.pat_yoy) },
  { key: "pat_qoq", label: "PAT QoQ", f: (r) => pct(r.pat_qoq) },
  { key: "eps", label: "EPS ₹", f: (r) => r.eps == null ? "–" : inr(r.eps, 2) },
  { key: "verdict", label: "Verdict", f: (r) => r.verdict ? `<span class="verdict v-${r.verdict}">${r.verdict}</span>` : '<span class="dim">–</span>' },
  { key: "nature", label: "Basis", l: 1, f: (r) => `<span class="dim">${esc((r.nature || "").slice(0, 4))}${r.revision ? " · rev" : ""}</span>` },
  { key: "filed", label: "Filed", l: 1, f: (r) => `<span class="dim">${esc(String(r.filed || "").slice(0, 11))}</span>`, sv: (r) => String(r.filed || "") },
];
async function renderResults(day) {
  const qes = (S.index.results_qe || []).slice(0, 3);
  $("#resScope").innerHTML = `<button data-s="day" class="${S.resScope === "day" ? "on" : ""}">This day</button>` +
    qes.map((q) => `<button data-s="${q}" class="${S.resScope === q ? "on" : ""}">${qLabel(q)} season</button>`).join("");
  $("#resScope").querySelectorAll("button").forEach((b) => b.onclick = () => { S.resScope = b.dataset.s; render(); });
  let rows;
  if (S.resScope === "day") rows = day.results || [];
  else rows = Object.values((await loadSeason("results", S.resScope)).rows || {});
  const total = rows.length;
  const cap = +$("#resCap").value, v = $("#resVerdict").value, q = $("#resQ").value.trim().toLowerCase();
  rows = rows.filter((r) => (!cap || (r.mcap ?? 0) >= cap) && (!v || r.verdict === v) &&
    (!q || r.sym.toLowerCase().includes(q) || (r.name || "").toLowerCase().includes(q)));
  $("#resNote").innerHTML = `${rows.length} of ${total} companies. Quarter figures in ₹ crore; consolidated where filed, else standalone. ` +
    `Verdict: <b>Strong</b> = PAT YoY ≥ 15% and revenue YoY ≥ 10%; <b>Weak</b> = PAT or revenue down YoY.` +
    (cap ? " Companies without a known market cap are hidden by the MCap filter." : "");
  table($("#resTable"), "res", RES_COLS, rows, ["pat_yoy", false]);
}

// ---------- Holdings ----------
const H_COLS = [
  { key: "sym", label: "Stock", l: 1, f: (r) => `${symLink(r.sym)}<span class="name">${esc(r.name)}</span>`, sv: (r) => r.sym },
  { key: "qe", label: "Quarter", l: 1, f: (r) => qLabel(r.qe) },
  { key: "promoter", label: "Promoter %", f: (r) => r.promoter == null ? "–" : r.promoter.toFixed(2) },
  { key: "promoter_chg", label: "Δ pp", f: (r) => pp(r.promoter_chg) },
  { key: "fii", label: "FII %", f: (r) => r.fii == null ? "–" : r.fii.toFixed(2) },
  { key: "fii_chg", label: "Δ pp", f: (r) => pp(r.fii_chg) },
  { key: "dii", label: "DII %", f: (r) => r.dii == null ? "–" : r.dii.toFixed(2) },
  { key: "dii_chg", label: "Δ pp", f: (r) => pp(r.dii_chg) },
  { key: "mf", label: "MF %", f: (r) => r.mf == null ? "–" : r.mf.toFixed(2) },
  { key: "mf_chg", label: "Δ pp", f: (r) => pp(r.mf_chg) },
  { key: "public", label: "Public %", f: (r) => r.public == null ? "–" : r.public.toFixed(2) },
];
async function renderHoldings(day) {
  const qes = (S.index.holdings_qe || []).slice(0, 2);
  $("#holdScope").innerHTML = `<button data-s="day" class="${S.holdScope === "day" ? "on" : ""}">Filed this day</button>` +
    qes.map((q) => `<button data-s="${q}" class="${S.holdScope === q ? "on" : ""}">${qLabel(q)}</button>`).join("");
  $("#holdScope").querySelectorAll("button").forEach((b) => b.onclick = () => { S.holdScope = b.dataset.s; render(); });
  let rows = S.holdScope === "day" ? (day.holdings || []) : Object.values((await loadSeason("holdings", S.holdScope)).rows || {});
  const min = +$("#holdMin").value, q = $("#holdQ").value.trim().toLowerCase();
  rows = rows.filter((r) => (!min || ["fii_chg", "dii_chg", "mf_chg", "promoter_chg"].some((k) => Math.abs(r[k] || 0) >= min)) &&
    (!q || r.sym.toLowerCase().includes(q) || (r.name || "").toLowerCase().includes(q)));
  table($("#holdTable"), "hold", H_COLS, rows, ["fii_chg", false]);
}

// ---------- Deals ----------
const D_COLS = [
  { key: "sym", label: "Stock", l: 1, f: (r) => `${symLink(r.sym)}<span class="name">${esc(r.name)}</span>`, sv: (r) => r.sym },
  { key: "client", label: "Client", l: 1, f: (r) => esc(r.client) + badge(r.itype) },
  { key: "side", label: "Side", l: 1, f: (r) => `<span class="${r.side === "BUY" ? "up" : "down"}">${esc(r.side)}</span>` },
  { key: "value_cr", label: "Value ₹cr", f: (r) => cr(r.value_cr) },
  { key: "qty", label: "Qty", f: (r) => inr(r.qty) },
  { key: "price", label: "Price ₹", f: (r) => inr(r.price, 2) },
  { key: "kind", label: "Type", l: 1, f: (r) => esc(r.kind) },
];
function renderDeals(day) {
  const inst = $("#instOnly").checked, side = $("#dealSide").value, q = $("#dealQ").value.trim().toLowerCase();
  const rows = (day.deals || []).filter((r) => (!inst || r.inst) && (!side || r.side === side) &&
    (!q || r.sym.toLowerCase().includes(q) || r.client.toLowerCase().includes(q)));
  table($("#dealTable"), "deal", D_COLS, rows, ["value_cr", false]);
}

// ---------- Stock fundamentals ----------
S.fund = {}; S.prices = null;
async function loadFund(sym) {
  const c = /^[A-Z]/i.test(sym) ? sym[0].toUpperCase() : "0";
  if (!(c in S.fund)) S.fund[c] = await getJSON(`data/fund/${c}.json`).catch(() => ({}));
  if (!S.prices) S.prices = await getJSON("data/fund/prices.json").catch(() => ({ p: {} }));
  return S.fund[c][sym] || null;
}
const ratio = (a, b) => (a == null || b == null || b === 0) ? null : a / b;
const grow = (a, b) => (a == null || b == null || b === 0) ? null : (a - b) / Math.abs(b) * 100;
const num1 = (v, d = 1) => v == null || !isFinite(v) ? '<span class="dim">–</span>' : inr(v, d);
const ptsChg = (v) => v == null || !isFinite(v) ? '<span class="dim">–</span>' :
  `<span class="${v > 0 ? "up" : v < 0 ? "down" : "dim"}">${v > 0 ? "+" : ""}${v.toFixed(1)} pts</span>`;
const shortDate = (iso) => iso ? new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "";
function ytdLabel(p) {
  if (!p?.s || !p?.e) return "";
  const m = Math.round((new Date(p.e) - new Date(p.s)) / 864e5 / 30.44);
  const e = new Date(p.e + "T00:00:00"); const fy = e.getMonth() + 1 >= 4 ? e.getFullYear() + 1 : e.getFullYear();
  return `${m === 6 ? "H1" : m === 9 ? "9M" : m === 12 ? "FY" : m + "M"} FY${String(fy).slice(2)}`;
}
function fundSection(sym, f) {
  if (!f) return `<h3>Fundamentals</h3><div class="empty fund-empty">Not collected yet for ${esc(sym)} — the desk is reading every company's latest results filing over the next few evenings.</div>`;
  const px = S.prices?.p?.[sym], pxDate = S.prices?.d;
  const q = f.q || {}, pq = f.pq || {}, py = f.py || {}, t = f.ttm || {};
  const mcap = f.sh && px ? f.sh * px / 1e7 : null;
  // P/E = market cap / 12-month net profit (falls back to price / 12-month EPS without a share count)
  const pe = mcap && t.pat > 0 ? mcap / t.pat : (!mcap && px && t.eps > 0 ? px / t.eps : null);
  const ps = mcap && t.rev > 0 ? mcap / t.rev : null;
  const tile = (label, val, note = "") => `<div class="ftile"><div class="fl">${label}</div><div class="fv">${val}</div>${note ? `<div class="fn">${note}</div>` : ""}</div>`;
  let peTxt = num1(pe), peNote = "last 4 quarters";
  if (px && (mcap ? t.pat : t.eps) != null && (mcap ? t.pat : t.eps) <= 0) { peTxt = '<span class="down">Loss</span>'; peNote = "12-month loss"; }
  else if (t.pat == null && t.eps == null) peNote = "needs 4 quarters";
  let h = `<h3>Fundamentals</h3><div class="fund-meta">${qLabel(f.qe)} results, ${esc((f.nat || "").toLowerCase())}${f.filed ? ` · filed ${esc(String(f.filed).slice(0, 11))}` : ""}${f.x ? ` · <a href="${esc(f.x)}" target="_blank" rel="noopener">filing ↗</a>` : ""}</div>`;
  h += `<div class="ftiles">` +
    tile("Price ₹", num1(px, 2), pxDate ? `close ${shortDate(pxDate)}` : "") +
    tile("Market cap ₹cr", mcap == null ? '<span class="dim">–</span>' : cr(Math.round(mcap))) +
    tile("P/E", peTxt, peNote) +
    tile("Mcap / Sales", num1(ps, 2), ps == null && t.rev == null ? "needs 4 quarters" : "last 4 quarters") +
    tile("EPS ₹ (12 m)", num1(t.eps, 2)) +
    tile("Sales ₹cr (12 m)", t.rev == null ? '<span class="dim">–</span>' : cr(t.rev)) + `</div>`;

  // quarter table: latest, previous, year-ago, QoQ, YoY
  const opm = (p) => f.finco ? null : ratio(p.op, p.rev) == null ? null : ratio(p.op, p.rev) * 100;
  const npm = (p) => ratio(p.pat, p.rev) == null ? null : ratio(p.pat, p.rev) * 100;
  const prevQ = pq.e ? qLabel(pq.e) : "Previous qtr", yaQ = py.e ? qLabel(py.e) : "Year ago";
  const row = (label, get, fmt, chg) => {
    const a = get(q), b = get(pq), c = get(py);
    return `<tr><td>${label}</td><td>${fmt(a)}</td><td>${fmt(b)}</td><td>${fmt(c)}</td><td>${chg(a, b)}</td><td>${chg(a, c)}</td></tr>`;
  };
  const crf = (v) => v == null ? '<span class="dim">–</span>' : cr(v);
  const pctf = (v) => v == null ? '<span class="dim">–</span>' : inr(v, 1) + "%";
  const g = (a, b) => pct(grow(a, b) == null ? null : Math.round(grow(a, b) * 10) / 10);
  const d = (a, b) => ptsChg(a == null || b == null ? null : a - b);
  h += `<div class="tablewrap"><table class="grid fund-q"><thead><tr><th>₹ crore</th><th>${qLabel(f.qe)}</th><th>${prevQ}</th><th>${yaQ}</th><th>QoQ</th><th>YoY</th></tr></thead><tbody>` +
    row("Sales", (p) => p.rev, crf, g) +
    (f.finco ? "" : row("Operating profit", (p) => p.op, crf, g) + row("OPM", opm, pctf, d)) +
    row("Net profit", (p) => p.pat, crf, g) +
    row("NPM", npm, pctf, d) +
    row("EPS ₹", (p) => p.eps, (v) => num1(v, 2), (a, b) => {
      // a split or bonus issue changes EPS but not profit: hide EPS growth that disagrees with profit growth
      const ge = grow(a, b), gp = grow(q.pat, a === q.eps && b === pq.eps ? pq.pat : py.pat);
      return ge != null && gp != null && Math.abs(ge - gp) > 25 ? '<span class="dim" title="Share count changed (split, bonus or new shares)">n/c</span>' : g(a, b);
    }) + `</tbody></table></div>`;
  if (f.finco) h += `<div class="fund-note">Bank / lender / insurer format: operating profit and OPM are not meaningful here, so they are left out.</div>`;

  // year to date and 12 months
  const y = f.ytd, yp = f.ytd_py;
  const bits = [];
  if (y && yp) bits.push(`<b>${ytdLabel(y)}</b> vs ${ytdLabel(yp)}: sales ${g(y.rev, yp.rev)}, net profit ${g(y.pat, yp.pat)}`
    + (!f.finco && y.op != null ? `, OPM ${pctf(opm(y))} (${d(opm(y), opm(yp))})` : ""));
  if (t.pat != null) bits.push(`<b>Last 12 months</b>: sales ₹${cr(t.rev)} cr, net profit ₹${cr(t.pat)} cr, NPM ${pctf(ratio(t.pat, t.rev) * 100)}`);
  if (bits.length) h += `<div class="fund-lines">${bits.map((b) => `<div>${b}</div>`).join("")}</div>`;

  // quality checks on the latest quarter
  const flags = [];
  const flag = (warn, text, tip) => flags.push(`<span class="fflag ${warn ? "warn" : "ok"}" title="${esc(tip)}">${warn ? "⚠ " : ""}${text}</span>`);
  if (q.pbt > 0 && q.oi != null && !f.finco) {
    const s = q.oi / q.pbt * 100;
    flag(s > 30, `Other income ${inr(s, 0)}% of profit before tax`, "Above 30% means a big part of profit is not from the core business (treasury income, one-offs).");
  }
  if (q.pbt > 0 && q.tax != null) {
    const r = q.tax / q.pbt * 100;
    flag(r < 15 || r > 40, `Tax rate ${inr(r, 0)}%`, "Normal is about 25%. Much lower or higher usually means one-off tax items that flatter or hurt the profit.");
  } else if (q.pbt != null && q.pbt <= 0) flag(true, "Loss before tax", "The company made a loss before tax this quarter.");
  if (!f.finco && q.fin != null && q.pbt != null) {
    if (q.fin <= Math.max(0.5, (q.rev || 0) * 0.005)) flag(false, "Almost no interest cost", "Finance cost below 0.5% of sales: little or no debt.");
    else { const ic = (q.pbt + q.fin) / q.fin; flag(ic < 2, `Interest cover ${inr(ic, 1)}×`, "(Profit before tax + interest) ÷ interest. Below 2× means debt is heavy for the profit."); }
  }
  if (q.exc && q.pbt) {
    const s = Math.abs(q.exc) / Math.abs(q.pbt) * 100;
    if (s >= 10) flag(true, `Exceptional items ₹${cr(q.exc)} cr (${inr(s, 0)}% of PBT)`, "One-off gains or losses: compare profit growth without them.");
  }
  if (flags.length) h += `<div class="fflags">${flags.join("")}</div>`;
  h += `<div class="fund-note">From the company's results filing. Operating profit = sales − operating costs (before other income, interest and depreciation). P/E and Mcap/Sales use the last 4 quarters and the latest close; numbers are read automatically, so open the filing before acting.</div>`;
  return h;
}

// ---------- Stock ----------
async function renderStock(sym) {
  const out = $("#stockOut");
  if (!S.search) {
    S.search = await getJSON("data/search.json").catch(() => ({}));
    $("#symList").innerHTML = Object.keys(S.search).sort().map((s) => `<option value="${esc(s)}">${esc(S.search[s].n || "")}</option>`).join("");
  }
  if (!sym) { out.innerHTML = '<div class="empty">Type a symbol to see its results, shareholding and filings from the last 120 days.</div>'; return; }
  $("#stockQ").value = sym;
  out.innerHTML = '<div class="empty">Loading…</div>';
  const res = [], hold = [];
  for (const qe of S.index.results_qe || []) { const s = await loadSeason("results", qe).catch(() => null); if (s?.rows?.[sym]) res.push(s.rows[sym]); }
  for (const qe of S.index.holdings_qe || []) { const s = await loadSeason("holdings", qe).catch(() => null); if (s?.rows?.[sym]) hold.push(s.rows[sym]); }
  const ev = (S.search[sym]?.e || []).slice().sort((a, b) => String(b[0]).localeCompare(String(a[0])));
  const name = S.search[sym]?.n || res[0]?.name || hold[0]?.name || "";
  const label = Object.fromEntries(TAGS);
  const fund = await loadFund(sym).catch(() => null);
  const fname = name || fund?.n || "";
  let h = `<div class="stockhead"><h2>${esc(sym)}</h2>${chartLink(sym)}<span class="co">${esc(fname)}</span>
    <a href="https://www.nseindia.com/get-quotes/equity?symbol=${encodeURIComponent(sym)}" target="_blank" rel="noopener">NSE page ↗</a>${await watchButton(sym, fname)}</div>`;
  const inst = await loadInst();
  const sd = inst ? inst.rows.filter((r) => r[2] === sym).map(([date, kind, , client, side, qty, price, value_cr, type]) =>
    ({ date, kind, client, side, qty, price, value_cr, type })) : [];
  if (!fund && !res.length && !hold.length && !ev.length && !sd.length) { out.innerHTML = h + '<div class="empty">Nothing recorded for this symbol yet.</div>'; wireWatchButton(sym, fname); return; }
  h += fundSection(sym, fund);
  if (res.length) h += `<h3>Quarterly results</h3><div class="tablewrap"><table class="grid" id="stRes"></table></div>`;
  if (sd.length) h += `<h3>Institutional bulk/block deals (last 90 days)</h3><div class="tablewrap"><table class="grid" id="stDeals"></table></div>`;
  if (hold.length) h += `<h3>Shareholding</h3><div class="tablewrap"><table class="grid" id="stHold"></table></div>`;
  h += `<h3>Filings (${ev.length})</h3><div class="timeline">` + (ev.length ? ev.map((e) =>
    `<article class="card" style="--c:var(--t-${e[1]})"><div class="head"><span class="pill">${label[e[1]] || e[1]}</span><span class="co">${esc(e[2])}</span><span class="time">${esc(String(e[0]).slice(0, 16))}</span></div>
     ${e[3] ? `<div class="txt">${esc(e[3])}</div>` : ""}<div class="chips">${e[5] ? `<span class="chip">₹${cr(e[5])} cr</span>` : ""}${e[4] ? `<a class="pdf" href="${esc(e[4])}" target="_blank" rel="noopener">Filing ↗</a>` : ""}</div></article>`).join("")
    : '<div class="empty">No tagged filings in the last 120 days.</div>') + "</div>";
  out.innerHTML = h;
  wireWatchButton(sym, fname);
  if (res.length) table($("#stRes"), "stres", [{ key: "qe", label: "Quarter", l: 1, f: (r) => qLabel(r.qe) }, ...RES_COLS.slice(1, 11)], res, ["qe", false]);
  if (hold.length) table($("#stHold"), "sthold", H_COLS.slice(1), hold, ["qe", false]);
  if (sd.length) table($("#stDeals"), "stdeals", [
    { key: "date", label: "Date", l: 1, f: (r) => esc(r.date) },
    { key: "client", label: "Institution", l: 1, f: (r) => esc(r.client) + badge(r.type) },
    { key: "side", label: "Side", l: 1, f: (r) => `<span class="${r.side === "BUY" ? "up" : "down"}">${esc(r.side)}</span>` },
    { key: "value_cr", label: "Value ₹cr", f: (r) => cr(r.value_cr) },
    { key: "qty", label: "Qty", f: (r) => inr(r.qty) },
    { key: "price", label: "Price ₹", f: (r) => inr(r.price, 2) },
    { key: "kind", label: "Type", l: 1, f: (r) => esc(r.kind) }], sd, ["date", false]);
}

// ---------- sign-in (same email/password as the F&O Desk) ----------
const CFG = window.FD_CONFIG || {};
const sb = (CFG.supabaseUrl && window.supabase) ? window.supabase.createClient(CFG.supabaseUrl, CFG.supabaseAnonKey, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
}) : null;
async function session() {
  if (!sb) return null;
  const { data } = await sb.auth.getSession();
  const ses = data.session;
  if (ses && CFG.email && ses.user.email.toLowerCase() !== CFG.email.toLowerCase()) return null;
  return ses;
}
function showSignIn(message) {
  document.querySelector("main").style.display = "none";
  document.querySelector(".tabs").style.display = "none";
  document.querySelector(".datebar").style.visibility = "hidden";
  $("#updated").textContent = "Private site";
  $("#signin").hidden = false;
  $("#siEmail").value = CFG.email || "";
  $("#siMsg").textContent = message || "";
  $("#siShow").onchange = (e) => { $("#siPass").type = e.target.checked ? "text" : "password"; };
  $("#signinForm").onsubmit = async (e) => {
    e.preventDefault();
    $("#siBtn").disabled = true; $("#siMsg").textContent = "";
    const { error } = await sb.auth.signInWithPassword({ email: $("#siEmail").value.trim(), password: $("#siPass").value });
    $("#siBtn").disabled = false;
    if (error) { $("#siMsg").textContent = /invalid/i.test(error.message) ? "Email or password is wrong." : `Could not sign in: ${error.message}`; return; }
    if (!(await session())) { $("#siMsg").textContent = "This email does not have access."; await sb.auth.signOut(); return; }
    location.reload();
  };
}

// ---------- watchlist (private, Supabase) ----------
const WATCH_DAYS = 90;
S.watch = null;
async function loadWatch(force = false) {
  if (S.watch && !force) return S.watch;
  const { data, error } = await sb.from("fd_watchlist").select("*").order("added_at", { ascending: false });
  if (error) throw new Error(/fd_watchlist/i.test(error.message)
    ? "the watchlist table is not set up yet (run supabase/001_watchlist.sql in Supabase → SQL Editor)" : error.message);
  S.watch = data;
  $("#wCount").textContent = data.length ? data.length : "";
  return data;
}
async function ensurePrices() {
  if (!S.prices) S.prices = await getJSON("data/fund/prices.json").catch(() => ({ p: {} }));
  return S.prices;
}
const istToday = () => new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10);
const addedDay = (w) => new Date(new Date(w.added_at).getTime() + 5.5 * 3600e3).toISOString().slice(0, 10);
const removeDay = (w) => new Date(new Date(w.added_at).getTime() + (w.keep_days || WATCH_DAYS) * 864e5 + 5.5 * 3600e3).toISOString().slice(0, 10);

function watchDialog({ sym, name, entry }) {
  const dlg = $("#wDlg");
  $("#wTitle").textContent = entry ? `Edit note: ${sym}` : `Add ${sym} to watchlist`;
  const px = S.prices?.p?.[sym];
  $("#wSub").textContent = entry ? `Added ${shortDate(addedDay(entry))}; removed automatically on ${shortDate(removeDay(entry))} unless you delete it first.`
    : `${name ? name + ". " : ""}${px ? `Price noted: ₹${inr(px, 2)} (close ${shortDate(S.prices.d)}). ` : ""}Stays for ${WATCH_DAYS} days or until you delete it.`;
  $("#wNote").value = entry?.note || "";
  $("#wErr").textContent = "";
  $("#wCancel").onclick = () => dlg.close();
  $("#wForm").onsubmit = async (e) => {
    e.preventDefault();
    $("#wSave").disabled = true;
    const note = $("#wNote").value.trim() || null;
    const q = entry ? sb.from("fd_watchlist").update({ note }).eq("id", entry.id)
      : sb.from("fd_watchlist").insert({ symbol: sym, name: name || null, note, price_added: px ?? null, price_date: px ? S.prices.d : null });
    const { error } = await q;
    $("#wSave").disabled = false;
    if (error) { $("#wErr").textContent = /duplicate|unique/i.test(error.message) ? `${sym} is already in the watchlist.` : /fd_watchlist/i.test(error.message) ? "The watchlist table is not set up yet (run supabase/001_watchlist.sql)." : error.message; return; }
    dlg.close();
    await loadWatch(true).catch(() => null);
    render();
  };
  dlg.showModal();
}
async function removeWatch(entry) {
  const { error } = await sb.from("fd_watchlist").delete().eq("id", entry.id);
  if (error) { alertBox(error.message); return; }
  await loadWatch(true).catch(() => null);
  render();
}
function alertBox(msg) {
  const out = $("#tab-" + currentTab());
  out.insertAdjacentHTML("afterbegin", `<div class="empty">${esc(msg)}</div>`);
}
async function watchButton(sym, name) {
  const list = await loadWatch().catch(() => null);
  if (!list) return "";
  const w = list.find((x) => x.symbol === sym);
  return w ? `<button class="wbtn on" id="wBtn" title="Open the Watchlist tab">★ In watchlist</button>`
    : `<button class="wbtn" id="wBtn" data-name="${esc(name)}">☆ Add to watchlist</button>`;
}
function wireWatchButton(sym, name) {
  const b = $("#wBtn"); if (!b) return;
  b.onclick = async () => {
    if (b.classList.contains("on")) { location.hash = "#watch"; return; }
    await ensurePrices();
    watchDialog({ sym, name });
  };
}

async function renderWatch() {
  const out = $("#watchOut");
  out.innerHTML = '<div class="empty">Loading…</div>';
  let list;
  try { list = await loadWatch(true); } catch (e) { out.innerHTML = `<div class="empty">Could not load the watchlist: ${esc(e.message)}</div>`; return; }
  if (!list.length) { out.innerHTML = '<div class="empty">Nothing here yet. Open a stock (tap its name anywhere) and press <b>☆ Add to watchlist</b>.</div>'; return; }
  await ensurePrices();
  if (!S.search) S.search = await getJSON("data/search.json").catch(() => ({}));
  const funds = Object.fromEntries(await Promise.all(list.map(async (w) => [w.symbol, await loadFund(w.symbol).catch(() => null)])));
  const label = Object.fromEntries(TAGS);
  const rows = list.map((w) => {
    const f = funds[w.symbol] || {}, q = f.q || {}, py = f.py || {}, t = f.ttm || {};
    const px = S.prices?.p?.[w.symbol] ?? null;
    const mcap = f.sh && px ? f.sh * px / 1e7 : null;
    const pe = mcap && t.pat > 0 ? mcap / t.pat : (!mcap && px && t.eps > 0 ? px / t.eps : null);
    const since = addedDay(w);
    const ev = (S.search[w.symbol]?.e || []).filter((e) => String(e[0]).slice(0, 10) >= since);
    const byTag = {}; ev.forEach((e) => byTag[e[1]] = (byTag[e[1]] || 0) + 1);
    const daysLeft = Math.max(0, Math.ceil((new Date(removeDay(w)) - new Date(istToday())) / 864e5));
    return {
      w, sym: w.symbol, name: w.name || f.n || S.search[w.symbol]?.n || "", added: w.added_at, since, daysLeft,
      p0: w.price_added, px, chg: grow(px, w.price_added), pe: t.pat != null && t.pat <= 0 ? -1 : pe,
      opm: f.finco || q.op == null || !q.rev ? null : q.op / q.rev * 100,
      salesYoy: grow(q.rev, py.rev), patYoy: grow(q.pat, py.pat), qe: f.qe, ev: ev.length, byTag,
    };
  });
  const cols = [
    { key: "sym", label: "Stock", l: 1, f: (r) => `${symLink(r.sym)}<span class="name">${esc(r.name)}</span>`, sv: (r) => r.sym },
    { key: "added", label: "Added", l: 1, f: (r) => `${esc(shortDate(r.since))}<span class="name">${r.daysLeft} days left</span>`, sv: (r) => r.added },
    { key: "p0", label: "Price added ₹", f: (r) => num1(r.p0, 2) },
    { key: "px", label: "Last close ₹", f: (r) => num1(r.px, 2) },
    { key: "chg", label: "Change", f: (r) => pct(r.chg == null ? null : Math.round(r.chg * 10) / 10) },
    { key: "pe", label: "P/E", f: (r) => r.pe === -1 ? '<span class="down">Loss</span>' : num1(r.pe) },
    { key: "opm", label: "OPM", f: (r) => r.opm == null ? '<span class="dim">–</span>' : inr(r.opm, 1) + "%" },
    { key: "salesYoy", label: "Sales YoY", f: (r) => pct(r.salesYoy == null ? null : Math.round(r.salesYoy * 10) / 10) },
    { key: "patYoy", label: "Profit YoY", f: (r) => pct(r.patYoy == null ? null : Math.round(r.patYoy * 10) / 10) },
    { key: "qe", label: "Quarter", l: 1, f: (r) => r.qe ? `<span class="dim">${qLabel(r.qe)}</span>` : '<span class="dim">–</span>' },
    { key: "ev", label: "New filings", l: 1, f: (r) => r.ev ? Object.entries(r.byTag).map(([t, n]) =>
        `<span class="wtag" style="--c:var(--t-${t})">${esc(label[t] || t)}${n > 1 ? " ×" + n : ""}</span>`).join("") : '<span class="dim">none</span>' },
    { key: "note", label: "Note", l: 1, f: (r) => `<span class="wnote">${r.w.setup ? `<span class="dim">Sector Strength: ${esc(r.w.setup)}${r.w.buy ? `, buy ${r.w.buy_is_trigger ? "above " : ""}${inr(r.w.buy, 2)}, stop ${inr(r.w.stop, 2)}` : ""}</span><br>` : ""}${esc(r.w.note || "")}</span>`, sv: (r) => r.w.note || "" },
    { key: "act", label: "", l: 1, f: (r) => `<button class="wact" data-edit="${r.w.id}" title="Edit note">✎</button><button class="wact del" data-del="${r.w.id}" title="Delete from watchlist">Delete</button>`, sv: () => 0 },
  ];
  out.innerHTML = '<div class="tablewrap"><table class="grid" id="watchTable"></table></div><p class="note">New filings: tagged NSE filings (results, orders, ratings, red flags…) since the day you added the stock; routine filings are left out. P/E, OPM and YoY growth are from the latest results (Fundamentals section of the Stock page).</p>';
  table($("#watchTable"), "watch", cols, rows, ["added", false]);
  out.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => { const w = list.find((x) => x.id == b.dataset.edit); watchDialog({ sym: w.symbol, name: w.name, entry: w }); });
  out.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => {
    const w = list.find((x) => x.id == b.dataset.del);
    if (b.dataset.sure) removeWatch(w);
    else { b.dataset.sure = 1; b.textContent = "Sure?"; setTimeout(() => { if (b.isConnected) { delete b.dataset.sure; b.textContent = "Delete"; } }, 3000); }
  });
}

// ---------- router ----------
function currentTab() { return (location.hash.slice(1).split("/")[0]) || "today"; }
let rendering = 0;
async function render() {
  const tab = currentTab();
  const my = ++rendering;
  document.querySelectorAll(".tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((s) => s.hidden = s.id !== "tab-" + tab);
  const i = S.index.dates.indexOf(S.date);
  $("#prevDay").disabled = i >= S.index.dates.length - 1;
  $("#nextDay").disabled = i <= 0;
  try {
    const day = S.date ? await loadDay(S.date) : { announcements: [], results: [], holdings: [], deals: [] };
    if (my !== rendering) return;
    if (tab === "today") { renderToday(day); renderFlowsCompact().catch(console.error); }
    else if (tab === "fii") await renderFii();
    else if (tab === "adding") await renderAdding();
    else if (tab === "results") await renderResults(day);
    else if (tab === "holdings") await renderHoldings(day);
    else if (tab === "deals") renderDeals(day);
    else if (tab === "watch") await renderWatch();
    else if (tab === "stock") await renderStock(decodeURIComponent(location.hash.split("/")[1] || "").toUpperCase());
  } catch (e) {
    console.error(e);
    $("#tab-" + tab).insertAdjacentHTML("afterbegin", `<div class="empty">Could not load data (${esc(e.message)}).</div>`);
  }
}

async function init() {
  if (sb) {
    const ses = await session();
    if (!ses) { showSignIn(); return; }
    $("#signOut").hidden = false;
    $("#signOut").onclick = async () => { await sb.auth.signOut(); location.reload(); };
    loadWatch().catch(() => null);
  }
  try { S.index = await getJSON("data/index.json?" + Date.now()); }
  catch (e) { $("#updated").textContent = "No data yet — the first collection has not run."; S.index = { dates: [] }; }
  const dates = S.index.dates || [];
  S.date = dates[0] || null;
  const partial = new Set(S.index.partial || []);
  $("#dateSel").innerHTML = dates.map((d) => `<option value="${d}">${niceDate(d)}${partial.has(d) ? " · partial" : ""}</option>`).join("");
  const lr = S.index.last_refresh;
  if (lr && lr.at) $("#updated").textContent = "Updated " + new Date(lr.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) +
    " IST · " + (lr.mode === "mid" ? "2 PM refresh (partial day)" : "end-of-day refresh");
  else if (S.index.updated) $("#updated").textContent = "Updated " + new Date(S.index.updated).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) + " IST";
  $("#dateSel").onchange = () => { S.date = $("#dateSel").value; S.tag = null; render(); };
  $("#prevDay").onclick = () => { const i = dates.indexOf(S.date); if (i < dates.length - 1) { S.date = dates[i + 1]; $("#dateSel").value = S.date; render(); } };
  $("#nextDay").onclick = () => { const i = dates.indexOf(S.date); if (i > 0) { S.date = dates[i - 1]; $("#dateSel").value = S.date; render(); } };
  ["#todayQ", "#resQ", "#holdQ", "#dealQ", "#addQ"].forEach((s) => $(s).addEventListener("input", render));
  ["#showOther", "#resCap", "#resVerdict", "#holdMin", "#instOnly", "#dealSide", "#addSide", "#addMin"].forEach((s) => $(s).addEventListener("change", render));
  $("#stockQ").addEventListener("change", () => { const v = $("#stockQ").value.trim().toUpperCase(); if (v) location.hash = "#stock/" + encodeURIComponent(v); });
  document.addEventListener("click", (e) => { const s = e.target.closest(".sym"); if (s) location.hash = "#stock/" + encodeURIComponent(s.dataset.sym); });
  window.addEventListener("hashchange", render);
  render();
}
init();


// ---------- manual refresh ----------
const GH = { repo: "vs916491-maker/NSE-fundamentals-desk", wf: "collect.yml" };
const GH_RUN_PAGE = `https://github.com/${GH.repo}/actions/workflows/${GH.wf}`;
const ls = { get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
             set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} } };
let refreshTimer = null;
const hhmm = (t) => new Date(t).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });

async function gh(path, opts = {}) {
  const tok = ls.get("ghToken");
  const r = await fetch(`https://api.github.com/repos/${GH.repo}${path}`, {
    ...opts, headers: { Accept: "application/vnd.github+json", ...(tok ? { Authorization: `Bearer ${tok}` } : {}), ...(opts.headers || {}) } });
  if (!r.ok && r.status !== 204) throw new Error(r.status === 401 || r.status === 403 ? "GitHub refused the token (check it has Actions: Read and write on this repo, and hasn't expired)" : `GitHub error ${r.status}`);
  return r.status === 204 ? null : r.json();
}

function panel(html) { const p = $("#refreshPanel"); p.innerHTML = `<button class="rclose" aria-label="Close">×</button>${html}`; p.hidden = false;
  p.querySelector(".rclose").onclick = () => { p.hidden = true; }; }

async function pollRun(since) {
  clearTimeout(refreshTimer);
  try {
    const d = await gh(`/actions/workflows/${GH.wf}/runs?event=workflow_dispatch&per_page=3`);
    const run = (d.workflow_runs || []).find((r) => new Date(r.created_at) >= new Date(since) - 60000);
    const btn = $("#refreshBtn");
    if (!run || run.status !== "completed") {
      btn.textContent = "↻ Refreshing…"; btn.classList.add("busy");
      btn.title = run ? `Running since ${hhmm(run.run_started_at || run.created_at)} · takes about 10 minutes` : "Starting…";
      refreshTimer = setTimeout(() => pollRun(since), 20000);
      return;
    }
    btn.classList.remove("busy"); btn.textContent = "↻ Refresh"; ls.set("refreshSince", null);
    if (run.conclusion === "success") {
      // the site is published by a second job right after; give it a moment
      panel(`<b>Refresh finished at ${hhmm(run.updated_at)}.</b><p>The new data is live within a minute.</p><button class="rbtn" id="rReload">Reload now</button>`);
      $("#rReload").onclick = () => location.reload();
    } else {
      panel(`<b>The refresh did not finish (${esc(run.conclusion)}).</b><p><a href="${esc(run.html_url)}" target="_blank" rel="noopener">See what happened on GitHub ↗</a></p>`);
    }
  } catch (e) {
    $("#refreshBtn").classList.remove("busy"); $("#refreshBtn").textContent = "↻ Refresh";
    panel(`<b>Could not check the refresh.</b><p>${esc(e.message)}</p>`);
  }
}

async function startRefresh() {
  const since = new Date().toISOString();
  try {
    await gh(`/actions/workflows/${GH.wf}/dispatches`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main", inputs: { args: "--auto --again" } }) });
  } catch (e) { panel(`<b>Refresh not started.</b><p>${esc(e.message)}</p><button class="rbtn ghost" id="rForget">Remove saved token</button>`);
    $("#rForget").onclick = () => { ls.set("ghToken", null); $("#refreshPanel").hidden = true; }; return; }
  ls.set("refreshSince", since);
  panel(`<b>Refresh started.</b><p>It takes about 10 minutes. Before 6:30 PM it's the partial (2 PM-style) refresh; after that it's the end-of-day refresh with the email. The button shows progress.</p>`);
  pollRun(since);
}

function refreshSetup() {
  panel(`<b>Refresh now</b>
    <p><a class="rbtn" href="${GH_RUN_PAGE}" target="_blank" rel="noopener">Open GitHub → Run workflow ↗</a></p>
    <p class="dim">On that page press <i>Run workflow</i>, then the green <i>Run workflow</i> button.</p>
    <hr><b>Or make this button one-click</b>
    <p>Paste a GitHub fine-grained token with access to only this repository and <i>Actions: Read and write</i>. It is saved in this browser only.</p>
    <input id="rTok" type="password" placeholder="github_pat_…" autocomplete="off"><button class="rbtn" id="rSave">Save and refresh</button>`);
  $("#rSave").onclick = () => { const t = $("#rTok").value.trim(); if (!t) return; ls.set("ghToken", t); startRefresh(); };
}

$("#refreshBtn").onclick = () => {
  if ($("#refreshBtn").classList.contains("busy")) { panel(`<b>Refresh in progress.</b><p>${esc($("#refreshBtn").title)}</p>`); return; }
  ls.get("ghToken") ? startRefresh() : refreshSetup();
};
if (ls.get("refreshSince") && ls.get("ghToken")) pollRun(ls.get("refreshSince"));
