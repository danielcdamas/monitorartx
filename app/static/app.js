/* Monitor RTX 5080 — frontend em tempo real (SSE + gráfico SVG) */
"use strict";

const STORES = [
  { id: "terabyte", label: "Terabyteshop", color: "var(--s-terabyte)", hex: "#3987e5" },
  { id: "kabum", label: "KaBuM!", color: "var(--s-kabum)", hex: "#199e70" },
  { id: "pichau", label: "Pichau", color: "var(--s-pichau)", hex: "#c98500" },
  { id: "amazon", label: "Amazon", color: "var(--s-amazon)", hex: "#008300" },
];
const storeById = Object.fromEntries(STORES.map((s) => [s.id, s]));

const fmtBRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const fmtBRL0 = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const fmtTime = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const fmtTimeS = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const fmtDay = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit" });
const fmtDayTime = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

const $ = (id) => document.getElementById(id);

let state = null;          // último snapshot recebido
let historyDays = 7;
let historyRows = [];      // linhas cruas de /api/history
let lastMessageAt = 0;

/* ------------------------------------------------------------------ helpers */

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function parseUTC(s) {
  if (!s) return null;
  // horas do histórico chegam sem timezone (UTC naive)
  if (!/[Zz+]/.test(s.slice(10))) s += "Z";
  return new Date(s);
}

/* ------------------------------------------------------------------- render */

function render() {
  if (!state) return;
  const offers = state.offers || [];
  const hasData = offers.length > 0;
  $("hero").hidden = !hasData;
  $("empty-state").hidden = hasData || (state.status || []).some((s) => s.ok);
  if (!hasData && !$("empty-state").hidden) {
    // primeira coleta ainda rodando
  }

  renderHero(offers);
  renderStatus(state.status || []);
  renderTable(offers);

  const t = parseUTC(state.last_cycle);
  $("stat-updated").textContent = t ? fmtTimeS.format(t) : "—";
}

function renderHero(offers) {
  const avail = offers.filter((o) => o.available);
  const best = state.best;
  const okStores = (state.status || []).filter((s) => s.ok).length;
  $("stat-stores").textContent = `${okStores} / ${(state.status || []).length}`;
  $("stat-offers").textContent = String(offers.length);
  if (!best) {
    $("best-price").textContent = "—";
    $("best-name").textContent = avail.length ? "" : "Nenhuma oferta disponível no momento";
    $("best-link").hidden = true;
    return;
  }
  $("best-price").textContent = fmtBRL.format(best.price);
  $("best-name").textContent = best.name;
  const badge = $("best-store");
  badge.textContent = best.store_label;
  badge.dataset.store = best.store;
  const link = $("best-link");
  link.hidden = false;
  link.href = best.url;
}

function renderStatus(statusList) {
  const row = $("status-row");
  row.replaceChildren();
  for (const st of statusList) {
    const meta = storeById[st.store] || { label: st.store_label };
    const chip = el("div", "status-chip");
    let icon = "●", detail;
    if (st.ok) {
      chip.classList.add("is-ok");
      const t = parseUTC(st.last_success);
      detail = `${st.offer_count} oferta${st.offer_count === 1 ? "" : "s"} · ${t ? fmtTime.format(t) : ""}`;
    } else if (st.error) {
      chip.classList.add("is-err");
      detail = "indisponível — " + st.error.slice(0, 60);
      chip.title = st.error;
    } else {
      chip.classList.add("is-wait");
      detail = "aguardando primeira coleta…";
    }
    chip.append(el("span", "status-icon", icon));
    const body = el("div");
    body.append(el("strong", "", meta.label), el("span", "detail", detail));
    chip.append(body);
    row.append(chip);
  }
}

function renderTable(offers) {
  const body = $("offers-body");
  body.replaceChildren();
  const bestUrl = state.best ? state.best.url : null;
  $("table-count").textContent = offers.length ? `(${offers.length})` : "";
  for (const o of offers) {
    const tr = el("tr");
    if (o.url === bestUrl && o.available) tr.classList.add("is-best");
    if (!o.available) tr.classList.add("is-unavailable");

    const tdStore = el("td");
    const badge = el("span", "store-badge", o.store_label);
    badge.dataset.store = o.store;
    tdStore.append(badge);

    const tdName = el("td");
    const nm = el("span", "prod-name", o.name);
    nm.title = o.name;
    tdName.append(nm);

    const tdPrice = el("td", "num price-cell", fmtBRL.format(o.price));
    const tdCard = el("td", "num", o.price_card ? fmtBRL.format(o.price_card) : "—");
    const tdStock = el("td");
    tdStock.append(el("span", o.available ? "stock-ok" : "stock-out", o.available ? "Em estoque" : "Esgotado"));

    const tdLink = el("td");
    const a = el("a", "prod-link", "Abrir ↗");
    a.href = o.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    tdLink.append(a);

    tr.append(tdStore, tdName, tdPrice, tdCard, tdStock, tdLink);
    body.append(tr);
  }
}

/* ----------------------------------------------------------------- gráfico */

const chart = {
  svg: $("chart"),
  wrap: $("chart-wrap"),
  tooltip: $("chart-tooltip"),
  grid: [],        // timestamps (ms) das colunas horárias
  series: {},      // store -> [{t, price} | null] alinhado ao grid
  geom: null,
};

function buildSeries() {
  const byStore = {};
  for (const row of historyRows) {
    const t = parseUTC(row.hour).getTime();
    (byStore[row.store] = byStore[row.store] || new Map()).set(t, row.price);
  }
  const allT = new Set();
  for (const m of Object.values(byStore)) for (const t of m.keys()) allT.add(t);
  if (!allT.size) { chart.grid = []; chart.series = {}; return; }

  const HOUR = 3600_000;
  const start = Math.min(...allT);
  const end = Math.max(Math.max(...allT), Date.now());
  const grid = [];
  for (let t = start; t <= end; t += HOUR) grid.push(t);
  // preço vale até ser alterado: forward-fill a partir do primeiro ponto de cada loja
  const series = {};
  for (const [store, m] of Object.entries(byStore)) {
    let last = null;
    series[store] = grid.map((t) => {
      if (m.has(t)) last = m.get(t);
      return last;
    });
  }
  chart.grid = grid;
  chart.series = series;
}

function niceTicks(min, max, n) {
  if (min === max) { min -= 1; max += 1; }
  const span = max - min;
  const step0 = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) ticks.push(v);
  return ticks;
}

function svgEl(tag, attrs) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  return n;
}

function drawChart() {
  buildSeries();
  const svg = chart.svg;
  svg.replaceChildren();
  const hasData = chart.grid.length > 0 && Object.keys(chart.series).length > 0;
  $("chart-empty").hidden = hasData;
  renderLegend();
  if (!hasData) { chart.geom = null; return; }

  const W = chart.wrap.clientWidth || 800;
  const H = 300;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const M = { top: 14, right: 110, bottom: 28, left: 66 };
  const iw = W - M.left - M.right;
  const ih = H - M.top - M.bottom;

  const values = Object.values(chart.series).flat().filter((v) => v != null);
  let vmin = Math.min(...values), vmax = Math.max(...values);
  const pad = Math.max((vmax - vmin) * 0.08, vmax * 0.005, 20);
  vmin -= pad; vmax += pad;

  const t0 = chart.grid[0], t1 = chart.grid[chart.grid.length - 1];
  const x = (t) => M.left + (t1 === t0 ? iw / 2 : ((t - t0) / (t1 - t0)) * iw);
  const y = (v) => M.top + ih - ((v - vmin) / (vmax - vmin)) * ih;
  chart.geom = { x, y, M, W, H, iw, ih };

  // gridlines + eixo Y
  for (const v of niceTicks(vmin, vmax, 5)) {
    svg.append(svgEl("line", { x1: M.left, x2: W - M.right, y1: y(v), y2: y(v), stroke: "#2c2c2a", "stroke-width": 1 }));
    const lbl = svgEl("text", { x: M.left - 8, y: y(v) + 4, "text-anchor": "end", fill: "#898781", "font-size": 11.5 });
    lbl.textContent = fmtBRL0.format(v);
    svg.append(lbl);
  }
  // linha de base
  svg.append(svgEl("line", { x1: M.left, x2: W - M.right, y1: M.top + ih, y2: M.top + ih, stroke: "#383835", "stroke-width": 1 }));

  // eixo X
  const spanMs = t1 - t0;
  const nXT = Math.min(6, chart.grid.length);
  const shortSpan = spanMs <= 36 * 3600_000;
  const seen = new Set();
  for (let i = 0; i < nXT; i++) {
    const t = t0 + (spanMs * i) / Math.max(nXT - 1, 1);
    const d = new Date(t);
    const label = shortSpan ? fmtTime.format(d) : fmtDay.format(d);
    if (seen.has(label)) continue;
    seen.add(label);
    const lbl = svgEl("text", { x: x(t), y: M.top + ih + 18, "text-anchor": "middle", fill: "#898781", "font-size": 11.5 });
    lbl.textContent = label;
    svg.append(lbl);
  }

  // linhas das séries (ordem fixa de lojas)
  const labelSlots = [];
  for (const s of STORES) {
    const data = chart.series[s.id];
    if (!data) continue;
    let d = "", started = false, lastPoint = null, nPoints = 0;
    data.forEach((v, i) => {
      if (v == null) return;
      const px = x(chart.grid[i]), py = y(v);
      d += (started ? " L" : "M") + px.toFixed(1) + " " + py.toFixed(1);
      started = true;
      nPoints++;
      lastPoint = { px, py, v };
    });
    if (!started) continue;
    if (nPoints === 1) {
      // um único ponto não desenha linha — mostra um marcador
      svg.append(svgEl("circle", { cx: lastPoint.px, cy: lastPoint.py, r: 4, fill: s.hex }));
    } else {
      svg.append(svgEl("path", { d, fill: "none", stroke: s.hex, "stroke-width": 2, "stroke-linejoin": "round" }));
    }
    if (lastPoint) labelSlots.push({ store: s, ...lastPoint });
  }

  // rótulos diretos no fim das linhas (evitando sobreposição)
  labelSlots.sort((a, b) => a.py - b.py);
  let prevY = -Infinity;
  for (const slot of labelSlots) {
    let ly = Math.max(slot.py, prevY + 14);
    ly = Math.min(ly, M.top + ih);
    prevY = ly;
    const lbl = svgEl("text", { x: slot.px + 8, y: ly + 4, fill: slot.store.hex, "font-size": 12, "font-weight": 600 });
    lbl.textContent = slot.store.label;
    svg.append(lbl);
  }

  // camadas do hover
  chart.hoverLine = svgEl("line", { y1: M.top, y2: M.top + ih, stroke: "#898781", "stroke-width": 1, "stroke-dasharray": "3 3", visibility: "hidden" });
  svg.append(chart.hoverLine);
  chart.hoverDots = STORES.map((s) => {
    const c = svgEl("circle", { r: 4, fill: s.hex, stroke: "#1a1a19", "stroke-width": 2, visibility: "hidden" });
    svg.append(c);
    return { store: s.id, node: c };
  });
}

function renderLegend() {
  const lg = $("chart-legend");
  lg.replaceChildren();
  for (const s of STORES) {
    if (chart.series[s.id] === undefined && historyRows.length) continue;
    const item = el("span", "legend-item");
    const key = el("span", "legend-key");
    key.style.setProperty("--kc", s.color);
    item.append(key, document.createTextNode(s.label));
    lg.append(item);
  }
}

function onChartHover(ev) {
  if (!chart.geom || !chart.grid.length) return;
  const rect = chart.svg.getBoundingClientRect();
  const px = ((ev.clientX - rect.left) / rect.width) * chart.geom.W;
  const { x, y, M, iw } = chart.geom;
  if (px < M.left - 10 || px > M.left + iw + 10) { hideTooltip(); return; }

  // coluna horária mais próxima
  let best = 0, bestD = Infinity;
  chart.grid.forEach((t, i) => {
    const d = Math.abs(x(t) - px);
    if (d < bestD) { bestD = d; best = i; }
  });
  const t = chart.grid[best];
  const cx = x(t);
  chart.hoverLine.setAttribute("x1", cx);
  chart.hoverLine.setAttribute("x2", cx);
  chart.hoverLine.setAttribute("visibility", "visible");

  const rows = [];
  for (const s of STORES) {
    const v = chart.series[s.id] ? chart.series[s.id][best] : null;
    const dot = chart.hoverDots.find((d) => d.store === s.id);
    if (v == null) { if (dot) dot.node.setAttribute("visibility", "hidden"); continue; }
    if (dot) {
      dot.node.setAttribute("cx", cx);
      dot.node.setAttribute("cy", y(v));
      dot.node.setAttribute("visibility", "visible");
    }
    rows.push({ s, v });
  }
  rows.sort((a, b) => a.v - b.v);

  const tt = chart.tooltip;
  tt.replaceChildren();
  tt.append(el("div", "tt-time", fmtDayTime.format(new Date(t))));
  for (const { s, v } of rows) {
    const row = el("div", "tt-row");
    const key = el("span", "tt-key");
    key.style.setProperty("--kc", s.color);
    row.append(key, el("span", "tt-val", fmtBRL.format(v)), el("span", "tt-store", s.label));
    tt.append(row);
  }
  tt.hidden = rows.length === 0;

  const wrapRect = chart.wrap.getBoundingClientRect();
  const relX = ((cx / chart.geom.W) * rect.width) + (rect.left - wrapRect.left);
  const flip = relX > wrapRect.width - 200;
  tt.style.left = flip ? `${relX - tt.offsetWidth - 14}px` : `${relX + 14}px`;
  tt.style.top = `${Math.max(4, ev.clientY - wrapRect.top - 30)}px`;
}

function hideTooltip() {
  chart.tooltip.hidden = true;
  if (chart.hoverLine) chart.hoverLine.setAttribute("visibility", "hidden");
  (chart.hoverDots || []).forEach((d) => d.node.setAttribute("visibility", "hidden"));
}

async function loadHistory() {
  try {
    const res = await fetch(`/api/history?days=${historyDays}`);
    const data = await res.json();
    historyRows = data.series || [];
    drawChart();
  } catch (e) {
    console.warn("histórico indisponível", e);
  }
}

/* ------------------------------------------------------- tempo real / ciclo */

function applySnapshot(snap) {
  state = snap;
  lastMessageAt = Date.now();
  render();
  loadHistory();
}

function connectSSE() {
  const conn = $("conn");
  const label = $("conn-label");
  const es = new EventSource("/api/stream");
  es.onopen = () => {
    conn.className = "conn is-live";
    label.textContent = "ao vivo";
  };
  es.onmessage = (ev) => {
    try { applySnapshot(JSON.parse(ev.data)); } catch { /* keepalive */ }
  };
  es.onerror = () => {
    conn.className = "conn is-off";
    label.textContent = "reconectando…";
    // EventSource reconecta sozinho
  };
}

// fallback: se o SSE ficar mudo por muito tempo, busca por polling
setInterval(async () => {
  const interval = (state && state.interval_seconds) || 180;
  if (Date.now() - lastMessageAt > (interval + 90) * 1000) {
    try {
      const res = await fetch("/api/offers");
      applySnapshot(await res.json());
    } catch { /* servidor fora */ }
  }
}, 30_000);

// contagem regressiva para a próxima coleta
setInterval(() => {
  const elx = $("next-update");
  if (!state || !state.last_cycle) { elx.textContent = ""; return; }
  const next = parseUTC(state.last_cycle).getTime() + state.interval_seconds * 1000;
  const remain = Math.round((next - Date.now()) / 1000);
  if (remain <= 0) {
    elx.textContent = "coletando…";
  } else {
    const m = String(Math.floor(remain / 60)).padStart(2, "0");
    const s = String(remain % 60).padStart(2, "0");
    elx.textContent = `próxima coleta em ${m}:${s}`;
  }
}, 1000);

/* --------------------------------------------------------------- controles */

$("refresh-btn").addEventListener("click", async (ev) => {
  const btn = ev.currentTarget;
  btn.disabled = true;
  try { await fetch("/api/refresh", { method: "POST" }); } catch { /* ignora */ }
  setTimeout(() => { btn.disabled = false; }, 5000);
});

document.querySelectorAll(".range-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".range-btn").forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    historyDays = Number(btn.dataset.days);
    loadHistory();
  });
});

chart.svg.addEventListener("pointermove", onChartHover);
chart.svg.addEventListener("pointerleave", hideTooltip);
new ResizeObserver(() => drawChart()).observe(chart.wrap);

/* ---------------------------------------------------------------- arranque */

connectSSE();
fetch("/api/offers").then((r) => r.json()).then(applySnapshot).catch(() => {});
