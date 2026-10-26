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
const symLink = (s) => `<span class="sym" data-sym="${esc(s)}">${esc(s)}</span>`;

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
  let h = `<div class="stockhead"><h2>${esc(sym)}</h2><span class="co">${esc(name)}</span>
    <a href="https://www.nseindia.com/get-quotes/equity?symbol=${encodeURIComponent(sym)}" target="_blank" rel="noopener">NSE page ↗</a></div>`;
  if (!res.length && !hold.length && !ev.length && !sd.length) { out.innerHTML = h + '<div class="empty">Nothing recorded for this symbol yet.</div>'; return; }
  const inst = await loadInst();
  const sd = inst ? inst.rows.filter((r) => r[2] === sym).map(([date, kind, , client, side, qty, price, value_cr, type]) =>
    ({ date, kind, client, side, qty, price, value_cr, type })) : [];
  if (res.length) h += `<h3>Quarterly results</h3><div class="tablewrap"><table class="grid" id="stRes"></table></div>`;
  if (sd.length) h += `<h3>Institutional bulk/block deals (last 90 days)</h3><div class="tablewrap"><table class="grid" id="stDeals"></table></div>`;
  if (hold.length) h += `<h3>Shareholding</h3><div class="tablewrap"><table class="grid" id="stHold"></table></div>`;
  h += `<h3>Filings (${ev.length})</h3><div class="timeline">` + (ev.length ? ev.map((e) =>
    `<article class="card" style="--c:var(--t-${e[1]})"><div class="head"><span class="pill">${label[e[1]] || e[1]}</span><span class="co">${esc(e[2])}</span><span class="time">${esc(String(e[0]).slice(0, 16))}</span></div>
     ${e[3] ? `<div class="txt">${esc(e[3])}</div>` : ""}<div class="chips">${e[5] ? `<span class="chip">₹${cr(e[5])} cr</span>` : ""}${e[4] ? `<a class="pdf" href="${esc(e[4])}" target="_blank" rel="noopener">Filing ↗</a>` : ""}</div></article>`).join("")
    : '<div class="empty">No tagged filings in the last 120 days.</div>') + "</div>";
  out.innerHTML = h;
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
    else if (tab === "stock") await renderStock(decodeURIComponent(location.hash.split("/")[1] || "").toUpperCase());
  } catch (e) {
    console.error(e);
    $("#tab-" + tab).insertAdjacentHTML("afterbegin", `<div class="empty">Could not load data (${esc(e.message)}).</div>`);
  }
}

async function init() {
  try { S.index = await getJSON("data/index.json?" + Date.now()); }
  catch (e) { $("#updated").textContent = "No data yet — the first collection has not run."; S.index = { dates: [] }; }
  const dates = S.index.dates || [];
  S.date = dates[0] || null;
  $("#dateSel").innerHTML = dates.map((d) => `<option value="${d}">${niceDate(d)}</option>`).join("");
  if (S.index.updated) $("#updated").textContent = "Updated " + new Date(S.index.updated).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) + " IST";
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
