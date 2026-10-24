"use strict";
const $ = (s) => document.querySelector(s);
const TAGS = [
  ["Results", "Results"], ["Order", "Orders"], ["Penalty", "Penalties"], ["Buyback", "Buybacks"],
  ["Rating", "Ratings"], ["RedFlag", "Red flags"], ["Management", "Management"], ["Other", "Routine"],
];
const S = {
  index: null, date: null, days: {}, seasons: { results: {}, holdings: {} }, search: null,
  tag: null, resScope: "day", holdScope: "day", sort: {},
};

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
  { key: "client", label: "Client", l: 1, f: (r) => esc(r.client) },
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
  if (!res.length && !hold.length && !ev.length) { out.innerHTML = h + '<div class="empty">Nothing recorded for this symbol yet.</div>'; return; }
  if (res.length) h += `<h3>Quarterly results</h3><div class="tablewrap"><table class="grid" id="stRes"></table></div>`;
  if (hold.length) h += `<h3>Shareholding</h3><div class="tablewrap"><table class="grid" id="stHold"></table></div>`;
  h += `<h3>Filings (${ev.length})</h3><div class="timeline">` + (ev.length ? ev.map((e) =>
    `<article class="card" style="--c:var(--t-${e[1]})"><div class="head"><span class="pill">${label[e[1]] || e[1]}</span><span class="co">${esc(e[2])}</span><span class="time">${esc(String(e[0]).slice(0, 16))}</span></div>
     ${e[3] ? `<div class="txt">${esc(e[3])}</div>` : ""}<div class="chips">${e[5] ? `<span class="chip">₹${cr(e[5])} cr</span>` : ""}${e[4] ? `<a class="pdf" href="${esc(e[4])}" target="_blank" rel="noopener">Filing ↗</a>` : ""}</div></article>`).join("")
    : '<div class="empty">No tagged filings in the last 120 days.</div>') + "</div>";
  out.innerHTML = h;
  if (res.length) table($("#stRes"), "stres", [{ key: "qe", label: "Quarter", l: 1, f: (r) => qLabel(r.qe) }, ...RES_COLS.slice(1, 11)], res, ["qe", false]);
  if (hold.length) table($("#stHold"), "sthold", H_COLS.slice(1), hold, ["qe", false]);
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
    if (tab === "today") renderToday(day);
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
  ["#todayQ", "#resQ", "#holdQ", "#dealQ"].forEach((s) => $(s).addEventListener("input", render));
  ["#showOther", "#resCap", "#resVerdict", "#holdMin", "#instOnly", "#dealSide"].forEach((s) => $(s).addEventListener("change", render));
  $("#stockQ").addEventListener("change", () => { const v = $("#stockQ").value.trim().toUpperCase(); if (v) location.hash = "#stock/" + encodeURIComponent(v); });
  document.addEventListener("click", (e) => { const s = e.target.closest(".sym"); if (s) location.hash = "#stock/" + encodeURIComponent(s.dataset.sym); });
  window.addEventListener("hashchange", render);
  render();
}
init();
