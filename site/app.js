const SVG = "http://www.w3.org/2000/svg";

function el(name, attrs = {}, text) {
  const node = document.createElement(name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  if (text != null) node.textContent = text;
  return node;
}

function svg(name, attrs = {}) {
  const node = document.createElementNS(SVG, name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
  return node;
}

function money(value) {
  return `$${Number(value).toFixed(2)}`;
}

function shortDate(iso) {
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const [, month, day] = iso.split("-").map(Number);
  return `${day} ${months[month - 1]}`;
}

function formatDate(iso) {
  if (!iso) return "";
  const [year, month, day] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.toLocaleDateString("en-AU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function renderCards(cards) {
  const host = document.getElementById("cards");
  host.replaceChildren();
  cards.forEach((card) => {
    const article = el("article", { class: `card ${card.status}` });
    const top = el("div", { class: "card-top" });
    top.append(el("p", { class: "eyebrow" }, card.eyebrow));
    top.append(el("p", { class: `pill ${card.status}` }, card.status_label));
    article.append(top);
    article.append(el("h3", {}, card.title));
    article.append(el("p", { class: "value" }, card.value));
    article.append(el("p", { class: "detail" }, card.detail));
    article.append(el("p", { class: "action" }, card.action));
    host.append(article);
  });
}

function ticks(min, max, count) {
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, index) => min + step * index);
}

function renderWeek(chart) {
  const host = document.getElementById("chart-week");
  const points = chart.points;
  const prices = points.map((point) => point.price_aud);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const wrap = el("div", { class: "week", role: "img", "aria-label": chart.lead });
  points.forEach((point) => {
    const col = el("div", { class: `week-col ${point.role}` });
    col.append(el("span", { class: "week-value" }, money(point.price_aud)));
    const track = el("div", { class: "week-track" });
    const height = 28 + ((point.price_aud - min) / (max - min || 1)) * 72;
    const bar = el("div", { class: "week-bar" });
    bar.style.setProperty("--size", `${height}%`);
    track.append(bar);
    col.append(track);
    col.append(el("span", { class: "week-day" }, point.label));
    wrap.append(col);
  });
  host.className = "chart";
  host.replaceChildren(wrap, dataTable(
    ["Day", "Average price"],
    points.map((point) => [point.day, money(point.price_aud)]),
  ));
}

function renderWholesale(chart) {
  const host = document.getElementById("chart-wholesale");
  const points = chart.points;
  const width = 640;
  const height = 300;
  const pad = { l: 52, r: 16, t: 28, b: 36 };
  const values = points.flatMap((point) => [point.pump_aud, point.wholesale_aud]);
  const min = Math.min(...values) - 0.05;
  const max = Math.max(...values) + 0.08;
  const plotH = height - pad.t - pad.b;
  const y = (value) => pad.t + (max - value) / (max - min) * plotH;
  const picture = svg("svg", { viewBox: `0 0 ${width - pad.l} ${height}`, role: "img" });
  picture.append(svg("title", {}, chart.lead));
  const yTicks = ticks(min, max, 4);
  yTicks.forEach((tick) => {
    const yPos = y(tick);
    picture.append(svg("line", { x1: 0, x2: width - pad.l - pad.r, y1: yPos, y2: yPos, stroke: "#e4d8c6" }));
  });
  const xShift = (index) => (points.length === 1 ? (width - pad.l - pad.r) / 2 : index / (points.length - 1) * (width - pad.l - pad.r));
  const pathFor = (key) => points.map((point, index) => `${index === 0 ? "M" : "L"} ${xShift(index).toFixed(1)} ${y(point[key]).toFixed(1)}`).join(" ");
  picture.append(svg("path", { d: pathFor("wholesale_aud"), fill: "none", stroke: "#2f5d7a", "stroke-width": 2.5 }));
  picture.append(svg("path", { d: pathFor("pump_aud"), fill: "none", stroke: "#c2410c", "stroke-width": 2.5 }));
  const frame = el("div", { class: "line-chart" });
  const legend = el("div", { class: "legend" });
  [["pump", "Pump"], ["wholesale", "Wholesale"]].forEach(([kind, name]) => {
    const item = el("span", { class: `legend-item ${kind}` }, name);
    legend.append(item);
  });
  frame.append(legend);
  const plot = el("div", { class: "line-plot" });
  const yAxis = el("div", { class: "y-axis" });
  yTicks.slice().reverse().forEach((tick) => yAxis.append(el("span", {}, money(tick))));
  plot.append(yAxis);
  plot.append(picture);
  frame.append(plot);
  const axis = el("div", { class: "x-axis" });
  [0, Math.floor((points.length - 1) / 2), points.length - 1].forEach((index) => {
    axis.append(el("span", {}, shortDate(points[index].week)));
  });
  frame.append(axis);
  host.className = "chart";
  host.replaceChildren(frame, dataTable(
    ["Week", "Pump", "Wholesale"],
    points.map((point) => [point.week, money(point.pump_aud), money(point.wholesale_aud)]),
  ));
}

function renderRegions(chart) {
  const host = document.getElementById("chart-regions");
  const points = chart.points;
  const prices = points.map((point) => point.price_aud);
  const min = Math.min(...prices) * 0.92;
  const max = Math.max(...prices);
  const wrap = el("div", { class: "regions", role: "img", "aria-label": chart.lead });
  points.forEach((point) => {
    const row = el("div", { class: `region ${point.kind}` });
    row.append(el("span", { class: "region-name" }, point.region));
    const track = el("div", { class: "region-track" });
    const bar = el("div", { class: "region-bar" });
    const length = ((point.price_aud - min) / (max - min || 1)) * 100;
    bar.style.width = `${Math.max(length, 4)}%`;
    track.append(bar);
    row.append(track);
    row.append(el("span", { class: "region-price" }, money(point.price_aud)));
    wrap.append(row);
  });
  host.className = "chart";
  host.replaceChildren(wrap, dataTable(
    ["Region", "Average price"],
    points.map((point) => [point.region, money(point.price_aud)]),
  ));
}

function dataTable(headers, rows) {
  const table = el("table");
  const head = el("tr");
  headers.forEach((header) => head.append(el("th", {}, header)));
  table.append(head);
  rows.forEach((row) => {
    const line = el("tr");
    row.forEach((cell) => line.append(el("td", {}, String(cell))));
    table.append(line);
  });
  return table;
}

async function main() {
  const response = await fetch("data/dashboard.json");
  if (!response.ok) {
    document.getElementById("kicker").textContent = "The figures could not be loaded.";
    return;
  }
  const data = await response.json();
  document.getElementById("kicker").textContent = data.kicker;
  document.getElementById("headline").textContent = data.headline;
  document.getElementById("dek").textContent = data.dek;
  document.title = `${data.headline} — Fuel Shock Radar`;
  renderCards(data.cards);
  document.getElementById("week-title").textContent = data.charts.week.title;
  document.getElementById("week-lead").textContent = data.charts.week.lead;
  document.getElementById("wholesale-title").textContent = data.charts.wholesale.title;
  document.getElementById("wholesale-lead").textContent = data.charts.wholesale.lead;
  document.getElementById("regions-title").textContent = data.charts.regions.title;
  document.getElementById("regions-lead").textContent = data.charts.regions.lead;
  renderWeek(data.charts.week);
  renderWholesale(data.charts.wholesale);
  renderRegions(data.charts.regions);
  document.getElementById("as-of").textContent = `Prices published through ${formatDate(data.footer.as_of)}.`;
  document.getElementById("attribution").textContent = data.footer.attribution;
  document.getElementById("methods").href = data.footer.methods_url;
}

main();
