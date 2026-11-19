/*
 * Adaptive Audio tester. The curve is worked out by the integration's own schedule.py and
 * curve.py, run in the browser with Pyodide (the Pages build copies them into py/), so this
 * page always agrees with the integration. The settings live in the URL hash, so a link
 * (including the one on the integration's setup page) opens with them filled in.
 */
"use strict";

const GLUE = `
import json, sys
sys.path.insert(0, "/home/pyodide")
from av import curve, schedule
from av.const import DEFAULTS

def compute(text):
    o = json.loads(text)
    clock = lambda v: schedule.parse_clock(v) if v else None
    rise, set_ = clock(o.pop("rise", None)), clock(o.pop("set", None))
    out = {"error": None, "samples": [], "marks": []}
    try:
        fn, marks = curve.builder(o, rise, set_)
        out["samples"] = [round(fn(m % 1440), 2) for m in range(0, 1441, 2)]
        out["marks"] = marks
    except schedule.ScheduleError as err:
        out["error"] = str(err)
    except Exception as err:  # a half-typed value; say so rather than break the page
        out["error"] = f"these settings can't be used ({err})"
    if curve.opt(o, "cap_enabled"):
        try:
            out["cap"] = list(curve.cap_window(o))
            out["cap_volume"] = float(curve.opt(o, "cap_volume"))
        except Exception:
            pass
    out["quiet"] = float(curve.opt(o, "quiet_volume"))
    return json.dumps(out)

defaults = json.dumps(DEFAULTS)
`;
const STEP = 2; // minutes between samples, matching range(0, 1441, 2) above
const PY_FILES = ["const.py", "schedule.py", "curve.py"];
const ANCHOR_KEYS = ["wake", "evening", "bedtime"];

// ---- fields: the same labels and help as the integration's setup page ----------------------
const simple = (o) => o.schedule_type !== "custom";
const SECTIONS = [
  {
    title: "Schedule",
    fields: [
      { key: "schedule_type", type: "tabs", label: "Type",
        options: [["simple", "Morning, evening and night"], ["custom", "My own times"]],
        help: "Morning, evening and night: set three volumes, and when each one starts. My own times: type a list of times and volumes." },
      { key: "curve", type: "tabs", label: "How the volume changes",
        options: [["sigmoid", "Smoothly"], ["linear", "Steadily"], ["steps", "All at once"]],
        help: "Smoothly eases in and out. Steadily changes at an even rate. All at once jumps at the set time." },
      { key: "day_volume", type: "pct", label: "Daytime volume", help: "Starts at Morning.", show: simple },
      { key: "use_evening", type: "bool", label: "Use a separate evening volume", show: simple },
      { key: "evening_volume", type: "pct", label: "Evening volume", help: "Starts at Evening.", show: (o) => simple(o) && o.use_evening },
      { key: "night_volume", type: "pct", label: "Night volume", help: "Starts at Bedtime.", show: simple },
      { key: "points", type: "text", label: "My own times", show: (o) => !simple(o),
        help: "One per line: a time, then a volume. You can use sunrise or sunset, plus or minus minutes. For example: 07:00 20, sunrise+30 25, sunset-45 30, 22:00 15." },
    ],
  },
  {
    title: "Times", show: simple,
    fields: [
      { anchor: "wake", type: "anchor", label: "Morning", help: "When the daytime volume starts." },
      { anchor: "evening", type: "anchor", label: "Evening", help: "When the evening volume starts.", show: (o) => o.use_evening },
      { anchor: "bedtime", type: "anchor", label: "Bedtime", help: "When the night volume starts." },
    ],
  },
  {
    title: "Sunrise and sunset", show: (o) => !simple(o),
    fields: [
      { key: "rise", type: "time", label: "Sunrise", help: "Used by lines like sunrise+30. Home Assistant uses today's times for your location." },
      { key: "set", type: "time", label: "Sunset" },
    ],
  },
  {
    title: "Quiet mode and night cap",
    fields: [
      { key: "quiet_volume", type: "pct", label: "Quiet volume", help: "The volume while quiet mode is on. Speakers can't go above it." },
      { key: "cap_enabled", type: "bool", label: "Night cap", help: "Sets a maximum volume during the hours below." },
      { key: "cap_volume", type: "pct", label: "Night cap volume", help: "Speakers can't go above this during night cap hours.", show: (o) => o.cap_enabled },
      { key: "cap_start", type: "time", label: "Night cap starts", show: (o) => o.cap_enabled },
      { key: "cap_end", type: "time", label: "Night cap ends", show: (o) => o.cap_enabled },
    ],
  },
];
// The settings the page keeps (and puts in the link).
const KEYS = ["schedule_type", "curve", "day_volume", "use_evening", "evening_volume", "night_volume", "points",
  ...ANCHOR_KEYS, "rise", "set", "quiet_volume", "cap_enabled", "cap_volume", "cap_start", "cap_end"];

let compute = null;
let DEFAULTS = {};
let opts = {};
let result = null;
let cursor = null; // minute under the pointer, or null for "now"
const shown = []; // [element, show(o)] pairs

// ---- settings <-> URL ------------------------------------------------------------------------
const hhmm = (v) => (v ? String(v).slice(0, 5) : "");
function fromHash() {
  const raw = location.hash.replace(/^#/, "");
  if (!raw) return {};
  try {
    const b64 = raw.replace(/-/g, "+").replace(/_/g, "/");
    const text = decodeURIComponent(escape(atob(b64 + "===".slice((b64.length + 3) % 4))));
    const o = JSON.parse(text);
    return o && typeof o === "object" ? o : {};
  } catch (e) {
    return {};
  }
}
function toHash(o) {
  return btoa(unescape(encodeURIComponent(JSON.stringify(o)))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function startingOptions(given) {
  const o = {};
  for (const k of KEYS) {
    if (ANCHOR_KEYS.includes(k)) {
      const d = DEFAULTS[k] || {};
      const g = (given[k] && typeof given[k] === "object") ? given[k] : {};
      o[k] = { time: hhmm(g.time ?? d.time), ramp: Number(g.ramp ?? d.ramp ?? 0) };
    } else if (k === "rise" || k === "set") {
      o[k] = hhmm(given[k]) || (k === "rise" ? "07:00" : "19:00");
    } else if (k === "cap_start" || k === "cap_end") {
      o[k] = hhmm(given[k] ?? DEFAULTS[k]);
    } else {
      o[k] = given[k] ?? DEFAULTS[k];
    }
  }
  return o;
}

// ---- building the form -----------------------------------------------------------------------
const h = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of kids) if (c) n.append(c);
  return n;
};
let uid = 0;
function fieldEl(f) {
  const id = `f${uid++}`;
  const help = f.help ? h("p", { class: "help", id: `${id}-h`, text: f.help }) : "";
  const described = f.help ? { "aria-describedby": `${id}-h` } : {};
  const wrap = h("div", { class: "field" });
  const set = (v) => { opts[f.key] = v; changed(); };

  if (f.type === "tabs") {
    const group = h("div", { class: "tabs", role: "group", "aria-labelledby": `${id}-l`, ...described });
    for (const [value, text] of f.options) {
      const b = h("button", { type: "button", "data-value": value, text });
      b.addEventListener("click", () => set(value));
      group.append(b);
    }
    wrap.append(h("label", { id: `${id}-l`, text: f.label }), help, group);
    wrap.sync = () => group.querySelectorAll("button").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.value === opts[f.key])));
  } else if (f.type === "pct") {
    const input = h("input", { type: "range", id, min: 0, max: 100, step: 1, ...described });
    const out = h("output", { for: id });
    input.addEventListener("input", () => set(Number(input.value)));
    wrap.append(h("label", { for: id, text: f.label }), help, h("div", { class: "slider" }, input, out));
    wrap.sync = () => { input.value = opts[f.key]; out.textContent = `${Math.round(opts[f.key])}%`; };
  } else if (f.type === "bool") {
    const input = h("input", { type: "checkbox", id, ...described });
    input.addEventListener("change", () => set(input.checked));
    wrap.append(h("label", { class: "check", for: id }, input, f.label), help);
    wrap.sync = () => { input.checked = !!opts[f.key]; };
  } else if (f.type === "time") {
    const input = h("input", { type: "time", id, ...described });
    input.addEventListener("change", () => { if (input.value) set(input.value); });
    wrap.append(h("label", { for: id, text: f.label }), help, input);
    wrap.sync = () => { input.value = opts[f.key]; };
  } else if (f.type === "text") {
    const input = h("textarea", { id, rows: 6, spellcheck: "false", ...described });
    input.addEventListener("input", () => set(input.value));
    wrap.append(h("label", { for: id, text: f.label }), help, input);
    wrap.sync = () => { if (document.activeElement !== input) input.value = opts[f.key] || ""; };
  } else if (f.type === "anchor") {
    const time = h("input", { type: "time", id: `${id}-t` });
    const ramp = h("input", { type: "number", id: `${id}-r`, min: 0, max: 480, step: 5, inputmode: "numeric" });
    const a = () => opts[f.anchor];
    time.addEventListener("change", () => { if (time.value) { a().time = time.value; changed(); } });
    ramp.addEventListener("input", () => {
      const v = Number(ramp.value);
      if (ramp.value !== "" && v >= 0 && v <= 480) { a().ramp = Math.round(v); changed(); }
    });
    wrap.append(
      h("h3", { text: f.label }), help,
      h("div", { class: "anchor" },
        h("div", {}, h("label", { for: `${id}-t`, text: "Time" }), time),
        h("div", {}, h("label", { for: `${id}-r`, text: "Change over (min)" }), ramp)),
    );
    wrap.sync = () => { time.value = a().time; if (document.activeElement !== ramp) ramp.value = a().ramp; };
  }
  return wrap;
}
const syncs = [];
function buildForm() {
  const form = document.getElementById("fields");
  const actions = form.querySelector(".actions");
  for (const s of SECTIONS) {
    const sec = h("section", {}, h("h2", { text: s.title }));
    if (s.show) shown.push([sec, s.show]);
    for (const f of s.fields) {
      const el = fieldEl(f);
      syncs.push(el.sync);
      if (f.show) shown.push([el, f.show]);
      sec.append(el);
    }
    form.insertBefore(sec, actions);
  }
}

// ---- the chart -------------------------------------------------------------------------------
const NS = "http://www.w3.org/2000/svg";
const svg = (tag, attrs, parent) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.append(n);
  return n;
};
const clockText = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(Math.round(m) % 60).padStart(2, "0")}`;
const nowMinute = () => { const d = new Date(); return d.getHours() * 60 + d.getMinutes(); };
// Spans of [a, b) minutes, split at midnight.
function spans(a, b) {
  a = ((a % 1440) + 1440) % 1440; b = ((b % 1440) + 1440) % 1440;
  if (a === b) return [[0, 1440]];
  return a < b ? [[a, b]] : [[a, 1440], [0, b]];
}
let geom = null;
function draw() {
  const box = document.getElementById("chart-box");
  box.textContent = "";
  if (!result) return;
  const W = Math.max(300, Math.round(box.clientWidth));
  const H = Math.round(Math.min(300, Math.max(190, W * 0.42)));
  const L = 40, R = 14, T = 22, B = 26;
  const s = result.samples;
  const capV = result.cap ? result.cap_volume : 0;
  let top = Math.max(10, ...s, capV, result.quiet) + 10;
  top = Math.min(100, Math.ceil(top / 10) * 10);
  const x = (m) => L + ((W - L - R) * m) / 1440;
  const y = (v) => T + (H - T - B) * (1 - v / top);
  geom = { W, H, L, R, T, B, x, y };

  const root = svg("svg", { id: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, tabindex: 0, role: "img",
    "aria-label": "The volume your speakers would start at through the day. Use the arrow keys to read it." });
  const step = top <= 50 ? 10 : 20;
  for (let v = 0; v <= top; v += step) {
    svg("line", { class: "grid", x1: L, x2: W - R, y1: y(v), y2: y(v) }, root);
    svg("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end" }, root).textContent = `${v}%`;
  }
  const every = W >= 520 ? 3 : 6;
  for (let hr = 0; hr <= 24; hr += every) {
    svg("line", { class: "grid", x1: x(hr * 60), x2: x(hr * 60), y1: T, y2: H - B }, root);
    const t = svg("text", { x: x(hr * 60), y: H - B + 17, "text-anchor": hr === 0 ? "start" : hr === 24 ? "end" : "middle" }, root);
    t.textContent = `${String(hr).padStart(2, "0")}:00`;
  }
  let lastEnd = -Infinity, row = 0;
  for (const m of [...result.marks].sort((p, q) => p.at - q.at)) {
    if (m.ramp) for (const [a, b] of spans(m.at - m.ramp / 2, m.at + m.ramp / 2))
      svg("rect", { class: "band", x: x(a), y: T, width: x(b) - x(a), height: H - T - B }, root);
    if (!m.name) continue;
    // A label that would run into the one before drops to a second row, inside the chart.
    const half = m.name.length * 3.4 + 4;
    row = x(m.at) - half < lastEnd && row === 0 ? 1 : 0;
    if (row === 0) lastEnd = x(m.at) + half;
    svg("text", { class: "mark", x: x(m.at), y: row ? T + 14 : T - 7, "text-anchor": "middle" }, root).textContent = m.name;
  }
  if (result.cap) {
    const yc = y(result.cap_volume);
    const parts = spans(result.cap[0], result.cap[1]);
    for (const [a, b] of parts) {
      svg("rect", { class: "capband", x: x(a), y: T, width: x(b) - x(a), height: yc - T }, root);
      svg("line", { class: "capline", x1: x(a), x2: x(b), y1: yc, y2: yc }, root);
    }
    const [a, b] = parts.reduce((p, q) => (q[1] - q[0] > p[1] - p[0] ? q : p));
    svg("text", { class: "cap", x: (x(a) + x(b)) / 2, y: yc - 5, "text-anchor": "middle" }, root).textContent = `night cap ${Math.round(result.cap_volume)}%`;
  }
  const yq = y(result.quiet);
  svg("line", { class: "quietline", x1: L, x2: W - R, y1: yq, y2: yq }, root);
  if (s.length) {
    const pts = s.map((v, i) => `${x(i * STEP).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    svg("polyline", { class: "curve", points: pts }, root);
  }
  geom.cursor = svg("line", { class: "cursor", y1: T, y2: H - B }, root);
  geom.dot = svg("circle", { class: "dot", r: 5 }, root);

  const pick = (ev) => {
    const r = root.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    cursor = Math.max(0, Math.min(1439, Math.round(((px - L) / (W - L - R)) * 1440)));
    readout();
  };
  root.addEventListener("pointermove", pick);
  root.addEventListener("pointerdown", pick);
  root.addEventListener("pointerleave", (ev) => { if (ev.pointerType === "mouse") { cursor = null; readout(); } });
  root.addEventListener("keydown", (ev) => {
    const d = { ArrowRight: 15, ArrowLeft: -15, PageUp: 60, PageDown: -60 }[ev.key];
    if (!d) return;
    ev.preventDefault();
    cursor = (((cursor ?? nowMinute()) + d) % 1440 + 1440) % 1440;
    readout();
  });
  box.append(root);
  readout();
}
function inCap(m) {
  return result.cap && spans(result.cap[0], result.cap[1]).some(([a, b]) => m >= a && m < b);
}
function readout() {
  const out = document.getElementById("readout");
  if (!result || !result.samples.length || !geom) { out.textContent = ""; return; }
  const m = cursor ?? nowMinute();
  const v = result.samples[Math.min(result.samples.length - 1, Math.round(m / STEP))];
  const { x, y } = geom;
  geom.cursor.setAttribute("x1", x(m)); geom.cursor.setAttribute("x2", x(m));
  geom.dot.setAttribute("cx", x(m)); geom.dot.setAttribute("cy", y(v));
  let text = `${clockText(m)}${cursor == null ? " (now)" : ""}: starts at ${Math.round(v)}%`;
  if (inCap(m) && v > result.cap_volume) text += `, held to ${Math.round(result.cap_volume)}% by the night cap`;
  out.textContent = text;
}

// ---- updates ---------------------------------------------------------------------------------
function changed() {
  for (const f of syncs) f();
  for (const [el, show] of shown) el.hidden = !show(opts);
  history.replaceState(null, "", `${location.pathname}${location.search}#${toHash(opts)}`);
  try {
    result = JSON.parse(compute(JSON.stringify(opts)));
  } catch (e) {
    result = { error: String(e), samples: [], marks: [], quiet: 0 };
  }
  const err = document.getElementById("error");
  err.hidden = !result.error;
  err.textContent = result.error ? `This schedule doesn't work: ${result.error}` : "";
  const legend = document.getElementById("legend");
  legend.hidden = !!result.error;
  legend.querySelector('[data-k="band"]').hidden = !result.marks.some((m) => m.ramp);
  legend.querySelector('[data-k="cap"]').hidden = !result.cap;
  if (result.error) {
    document.getElementById("chart-box").replaceChildren(h("p", { class: "chart-msg", text: "Fix the schedule to see the chart." }));
    document.getElementById("readout").textContent = "";
  } else draw();
}

// ---- style and theme -------------------------------------------------------------------------
const ROOT = document.documentElement;
const THEME_COLOURS = { lukas: ["#0d1a0e", "#f5eeee"], ha: ["#111111", "#fafafa"] };
const MOON = '<svg viewBox="0 0 512 512" aria-hidden="true"><path fill="currentColor" d="M32 256C32 132.2 132.3 32 255.8 32c11.36.0 29.7 1.668 40.9 3.746 9.616 1.777 11.75 14.63 3.279 19.44C245 86.5 211.2 144.6 211.2 207.8c0 109.7 99.71 193 208.3 172.3 9.561-1.805 16.28 9.324 10.11 16.95C387.9 448.6 324.8 480 255.8 480 132.1 480 32 379.6 32 256z"/></svg>';
const SUN = '<svg viewBox="2 2 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3V4m0 16v1M4 12H3M6.31412 6.31412 5.5 5.5m12.1859.81412L18.5 5.5M6.31412 17.69 5.5 18.5001M17.6859 17.69 18.5 18.5001M21 12H20m-4 0c0 2.2091-1.7909 4-4 4-2.20914.0-4-1.7909-4-4 0-2.20914 1.79086-4 4-4 2.2091.0 4 1.79086 4 4z"/></svg>';
const isLight = () => ROOT.getAttribute("data-theme") === "light";
const styleName = () => (ROOT.getAttribute("data-style") === "ha" ? "ha" : "lukas");
const store = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };
function syncChrome() {
  const btn = document.getElementById("theme-toggle");
  btn.innerHTML = isLight() ? MOON : SUN;
  btn.setAttribute("aria-label", isLight() ? "Switch to dark mode" : "Switch to light mode");
  document.querySelector('meta[name="theme-color"]').content = THEME_COLOURS[styleName()][isLight() ? 1 : 0];
  document.querySelectorAll("[data-style-btn]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.styleBtn === styleName())));
}
document.getElementById("theme-toggle").onclick = () => {
  const next = isLight() ? "dark" : "light";
  ROOT.setAttribute("data-theme", next);
  store("adaptive-audio-theme", next);
  syncChrome();
};
document.querySelectorAll("[data-style-btn]").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.styleBtn === "ha") ROOT.setAttribute("data-style", "ha"); else ROOT.removeAttribute("data-style");
  store("adaptive-audio-style", b.dataset.styleBtn);
  syncChrome();
  if (result && !result.error) draw(); // the chart's font size can change with the style
}));
syncChrome();

// ---- start -----------------------------------------------------------------------------------
document.getElementById("copy").addEventListener("click", async () => {
  const note = document.getElementById("copied");
  try {
    await navigator.clipboard.writeText(location.href);
    note.textContent = "Link copied.";
  } catch (e) {
    note.textContent = "Copy the address from your browser's address bar.";
  }
  setTimeout(() => { note.textContent = ""; }, 4000);
});
document.getElementById("reset").addEventListener("click", () => { opts = startingOptions({}); cursor = null; changed(); });
let resizeTimer = null;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (result && !result.error) draw(); }, 100); });
window.addEventListener("hashchange", () => {
  if (location.hash.slice(1) !== toHash(opts)) { opts = startingOptions(fromHash()); changed(); }
});
setInterval(() => { if (cursor == null) readout(); }, 60000);

(async function boot() {
  const msg = document.getElementById("chart-msg");
  try {
    const py = await loadPyodide();
    py.FS.mkdirTree("/home/pyodide/av");
    py.FS.writeFile("/home/pyodide/av/__init__.py", "");
    await Promise.all(PY_FILES.map(async (f) => {
      const r = await fetch(`py/${f}`);
      if (!r.ok) throw new Error(`${f}: ${r.status}`);
      py.FS.writeFile(`/home/pyodide/av/${f}`, await r.text());
    }));
    py.runPython(GLUE);
    compute = py.globals.get("compute");
    DEFAULTS = JSON.parse(py.globals.get("defaults"));
  } catch (e) {
    console.error(e);
    msg.textContent = "The calculator couldn't load. Check your connection and reload the page.";
    return;
  }
  buildForm();
  opts = startingOptions(fromHash());
  changed();
})();
