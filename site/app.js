/*
 * Adaptive Audio tester. The curve is worked out by the integration's own schedule.py and
 * curve.py, and the speaker's day by simulate.py, run in the browser with Pyodide (the Pages
 * build copies them into py/), so this page always agrees with the integration. The settings
 * live in the URL hash, so a link (including the one on the integration's setup page) opens
 * with them filled in.
 */
"use strict";

const GLUE = `
import json, sys
sys.path.insert(0, "/home/pyodide")
from av import curve, schedule, simulate
from av.const import DEFAULTS

SUN = {"sensor.sun_next_rising": "rise", "sensor.sun_next_setting": "set"}

def compute(text):
    o = json.loads(text)
    clock = lambda v: schedule.parse_clock(v) if v else None
    rise, set_ = clock(o.pop("rise", None)), clock(o.pop("set", None))
    ents = dict(o.pop("entities", None) or {})
    sim = o.pop("sim", None) or {}
    for eid, which in SUN.items():  # the sun sensors read today's sunrise and sunset
        m = rise if which == "rise" else set_
        if m is not None:
            ents[eid] = f"{m // 60:02d}:{m % 60:02d}"
    em = simulate.entity_minute_from(ents)
    out = {"error": None, "samples": [], "marks": [], "sim": None}
    try:
        fn, marks = curve.builder(o, rise, set_, em)
        out["samples"] = [round(fn(m % 1440), 2) for m in range(0, 1441, 2)]
        out["marks"] = marks
    except schedule.ScheduleError as err:
        out["error"] = str(err)
    except Exception as err:  # a half-typed value; say so rather than break the page
        out["error"] = f"these settings can't be used ({err})"
    if curve.opt(o, "cap_enabled") or o.get("cap_entity"):
        try:
            out["cap"] = list(curve.cap_window(o, em))
            out["cap_volume"] = float(curve.opt(o, "cap_volume"))
        except Exception:
            pass
    out["quiet"] = float(curve.opt(o, "quiet_volume"))
    if not out["error"]:
        try:
            out["sim"] = simulate.run(o, rise, set_, ents, sim.get("start") or {}, sim.get("events") or [], days=3)
        except Exception as err:
            out["sim_error"] = str(err)
    return json.dumps(out)

defaults = json.dumps(DEFAULTS)
`;
const STEP = 2; // minutes between samples, matching range(0, 1441, 2) above
const PY_FILES = ["const.py", "schedule.py", "curve.py", "simulate.py"];
const ANCHOR_KEYS = ["wake", "evening", "bedtime"];
const SUN_IDS = { rise: "sensor.sun_next_rising", set: "sensor.sun_next_setting" };
const ANCHOR_NAMES = { wake: "Morning", evening: "Evening", bedtime: "Bedtime" };

// ---- fields: the same labels and help as the integration's setup page ----------------------
const simple = (o) => o.schedule_type !== "custom";
const anchorTime = (a) => (o) => o[a].time;
const SECTIONS = [
  {
    title: "Speakers",
    fields: [
      { key: "skip_sources", type: "line", label: "Leave these inputs alone",
        help: "If a speaker is playing one of these inputs, its volume is never changed. Separate them with commas, for example: Line In" },
      { key: "idle_gap", type: "num", label: "Reset after being stopped for", min: 0, max: 720, unit: "min",
        help: "Once a speaker has been stopped this long, it starts at the scheduled volume the next time it plays. Shorter pauses keep your volume." },
      { key: "adapt", type: "bool", label: "Adjust while playing",
        help: "Playing speakers keep following the schedule as it changes through the day, no faster than the rate below. If you change a speaker's volume yourself, it stops following until it next starts playing. This is the same as the Adjust while playing switch." },
      { key: "autoreset", type: "num", label: "Follow the schedule again after", min: 0, max: 1440, unit: "min",
        help: "Only matters when Adjust while playing is on. If you change a speaker's volume yourself, it stops following the schedule. 0 waits until it next starts playing." },
      { key: "max_rate", type: "num", label: "Never change the volume faster than", min: 1, max: 100, unit: "%/min",
        help: "Playing speakers move toward the scheduled volume in 1% steps, at most this much each minute: while Adjust while playing is on, and when quiet mode turns off. Starting to play, turning quiet mode on and the night cap still change the volume straight away." },
    ],
  },
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
    title: "Sunrise and sunset",
    fields: [
      { key: "rise", type: "time", label: "Sunrise",
        help: "Used by lines like sunrise+30 and by Sun next rising and Sun next setting. Home Assistant uses today's times for your location." },
      { key: "set", type: "time", label: "Sunset" },
    ],
  },
  {
    title: "Quiet mode and night cap",
    fields: [
      { key: "quiet_volume", type: "pct", label: "Quiet volume", help: "The volume while quiet mode is on. Speakers can't go above it." },
      { key: "quiet_entity", type: "stateEntity", label: "Also turn on quiet mode with", fallbackId: "input_boolean.quiet_mode",
        startLabel: "Its state at the start of the day", text: true,
        help: "Optional. Quiet mode is also on while this is in the state below. Here it's a stand-in you change in the day below." },
      { key: "quiet_state", type: "line", label: "When it is", help: "Usually on.", show: (o) => !!o.quiet_entity },
      { key: "quiet_instant", type: "bool", label: "Return to the scheduled volume instantly",
        help: "When quiet mode turns off, playing speakers jump straight back to the scheduled volume. Leave it off to turn them back up gradually, no faster than the rate in Speakers." },
      { key: "cap_enabled", type: "bool", label: "Night cap", help: "Sets a maximum volume during the hours below. This is the same as the Night cap switch." },
      { key: "cap_entity", type: "stateEntity", label: "Also turn on the night cap with", fallbackId: "input_boolean.night_cap",
        startLabel: "Its state at the start of the day",
        help: "Optional. The night cap is also on while this is on. Here it's a stand-in you change in the day below." },
      { key: "cap_volume", type: "pct", label: "Night cap volume", help: "Speakers can't go above this during night cap hours.", show: (o) => o.cap_enabled || !!o.cap_entity },
      { key: "cap_start", type: "time", label: "Night cap starts", show: (o) => o.cap_enabled || !!o.cap_entity },
      { key: "cap_start_entity", type: "timeEntity", label: "Or start at a time from", slug: "night_cap_start", fallback: (o) => o.cap_start,
        show: (o) => o.cap_enabled || !!o.cap_entity },
      { key: "cap_end", type: "time", label: "Night cap ends", show: (o) => o.cap_enabled || !!o.cap_entity },
      { key: "cap_end_entity", type: "timeEntity", label: "Or end at a time from", slug: "night_cap_end", fallback: (o) => o.cap_end,
        show: (o) => o.cap_enabled || !!o.cap_entity },
    ],
  },
];
// The settings the page keeps (and puts in the link).
const KEYS = ["skip_sources", "idle_gap", "adapt", "autoreset", "max_rate",
  "schedule_type", "curve", "day_volume", "use_evening", "evening_volume", "night_volume", "points",
  ...ANCHOR_KEYS, "rise", "set", "quiet_volume", "quiet_entity", "quiet_state", "quiet_instant",
  "cap_enabled", "cap_entity", "cap_volume", "cap_start", "cap_start_entity", "cap_end", "cap_end_entity",
  "entities", "sim"];

// ---- the simulated day -----------------------------------------------------------------------
const ON_OFF = [["on", "On"], ["off", "Off"]];
const EXAMPLES = [
  { name: "An evening of music", start: { volume: 50 },
    events: [["17:30", "play"], ["18:20", "stop"], ["18:25", "play"], ["23:30", "stop"]] },
  { name: "Changed by hand", start: { volume: 50 },
    events: [["12:00", "play"], ["12:30", "volume", 60], ["14:00", "stop"], ["14:05", "play"], ["15:00", "stop"], ["16:00", "play"], ["17:00", "stop"]] },
  { name: "Quiet mode", start: { volume: 50 },
    events: [["19:30", "play"], ["20:30", "quiet", true], ["21:30", "quiet", false], ["22:30", "stop"]] },
  { name: "Night cap", start: { volume: 50 },
    events: [["21:00", "play"], ["21:00", "cap", true], ["22:30", "volume", 50], ["23:30", "volume", 60], ["23:45", "stop"]] },
  { name: "Turntable on Line In", start: { volume: 50 }, skip: "Line In",
    events: [["18:55", "source", "Line In"], ["19:00", "play"], ["20:00", "stop"], ["20:01", "source", "Spotify"], ["20:30", "play"], ["21:30", "stop"]] },
  { name: "Empty day", start: { volume: 50 }, events: [] },
];
const exampleSim = (ex) => ({
  start: { playing: false, volume: 50, source: "", enabled: true, quiet: false, ...ex.start },
  events: ex.events.map(([at, d, value]) => ({ at, do: d, value: value ?? null })),
});
// The kinds of event, as the menu shows them. Entity kinds are added per linked entity.
const EVENT_KINDS = [
  ["play", "Starts playing"],
  ["stop", "Stops"],
  ["volume", "Volume changed by hand to"],
  ["source", "Input switched to"],
  ["apply", "Set volume now is pressed"],
  ["enabled", "Adaptive audio switch turned"],
  ["quiet", "Quiet mode switch turned"],
  ["adapt", "Adjust while playing switch turned"],
  ["cap", "Night cap switch turned"],
];
function entityKinds(o) {
  const out = [];
  if (o.quiet_entity) out.push({ id: o.quiet_entity, label: "Quiet entity changes to", value: "text" });
  if (o.cap_entity) out.push({ id: o.cap_entity, label: "Night cap entity turns", value: "onoff" });
  const helpers = [];
  for (const a of ANCHOR_KEYS) helpers.push([o[a] && o[a].entity, `${ANCHOR_NAMES[a]} time helper changes to`]);
  helpers.push([o.cap_start_entity, "Night cap start helper changes to"], [o.cap_end_entity, "Night cap end helper changes to"]);
  for (const [id, label] of helpers) {
    if (id && !Object.values(SUN_IDS).includes(id) && !out.some((k) => k.id === id)) out.push({ id, label, value: "time" });
  }
  return out;
}

let compute = null;
let DEFAULTS = {};
let opts = {};
let result = null;
let cursor = null; // minute under the pointer on the day chart, or null for "now"
let simCursor = null; // the same for the speaker chart
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
      if (g.entity) o[k].entity = String(g.entity);
    } else if (k === "rise" || k === "set") {
      o[k] = hhmm(given[k]) || (k === "rise" ? "07:00" : "19:00");
    } else if (k === "cap_start" || k === "cap_end") {
      o[k] = hhmm(given[k] ?? DEFAULTS[k]);
    } else if (k.endsWith("_entity")) {
      if (given[k]) o[k] = String(given[k]);
    } else if (k === "entities") {
      o[k] = (given[k] && typeof given[k] === "object") ? { ...given[k] } : {};
    } else if (k === "sim") {
      const g = given.sim && typeof given.sim === "object" ? given.sim : null;
      o.sim = g ? { start: { ...exampleSim(EXAMPLES[0]).start, ...(g.start || {}) }, events: Array.isArray(g.events) ? g.events : [] }
        : exampleSim(EXAMPLES[0]);
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
const nextId = () => `f${uid++}`;
const select = (options, attrs = {}) => {
  const s = h("select", attrs);
  for (const [value, text] of options) s.append(h("option", { value, text }));
  return s;
};
const kindOf = (id) => (!id ? "" : id === SUN_IDS.rise ? "rise" : id === SUN_IDS.set ? "set" : "helper");

/* A time entity choice: nothing, a time helper (with its time), or a sun sensor. `get` and
   `put` read and write the entity id; `fallback` gives the time a new helper starts at. */
function timeEntityControls(id, get, put, slug, fallback) {
  const kind = select([["", "Nothing"], ["helper", "A time helper"], ["rise", "Sun next rising"], ["set", "Sun next setting"]], { id });
  const time = h("input", { type: "time", "aria-label": "The time helper's time" });
  const note = h("p", { class: "help mono-id" });
  const timeWrap = h("div", { class: "entity-time" }, h("label", { text: "The helper's time" }), time);
  kind.addEventListener("change", () => {
    const k = kind.value;
    if (!k) put(undefined);
    else if (k === "rise" || k === "set") put(SUN_IDS[k]);
    else {
      const cur = get();
      const eid = kindOf(cur) === "helper" ? cur : `input_datetime.${slug}`;
      if (!opts.entities[eid]) opts.entities[eid] = fallback(opts) || "12:00";
      put(eid);
    }
    changed();
  });
  time.addEventListener("change", () => { const eid = get(); if (eid && time.value) { opts.entities[eid] = time.value; changed(); } });
  const box = h("div", { class: "entity" }, kind, timeWrap, note);
  box.sync = () => {
    const eid = get();
    const k = kindOf(eid);
    kind.value = k;
    timeWrap.hidden = k !== "helper";
    note.hidden = !eid;
    if (k === "helper") {
      time.value = hhmm(opts.entities[eid]);
      note.textContent = `Stands in for ${eid}. Change its time during the day below.`;
    } else if (k) {
      note.textContent = `Follows ${k === "rise" ? "Sunrise" : "Sunset"} above (${eid}).`;
    }
  };
  return box;
}

function fieldEl(f) {
  const id = nextId();
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
  } else if (f.type === "num") {
    const input = h("input", { type: "number", id, min: f.min, max: f.max, step: 1, inputmode: "numeric", ...described });
    input.addEventListener("input", () => {
      const v = Number(input.value);
      if (input.value !== "" && v >= f.min && v <= f.max) set(Math.round(v));
    });
    wrap.append(h("label", { for: id, text: f.label }), help, h("div", { class: "unit" }, input, h("span", { text: f.unit })));
    wrap.sync = () => { if (document.activeElement !== input) input.value = opts[f.key]; };
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
  } else if (f.type === "line") {
    const input = h("input", { type: "text", id, spellcheck: "false", ...described });
    input.addEventListener("input", () => set(input.value));
    wrap.append(h("label", { for: id, text: f.label }), help, input);
    wrap.sync = () => { if (document.activeElement !== input) input.value = opts[f.key] || ""; };
  } else if (f.type === "text") {
    const input = h("textarea", { id, rows: 6, spellcheck: "false", ...described });
    input.addEventListener("input", () => set(input.value));
    wrap.append(h("label", { for: id, text: f.label }), help, input);
    wrap.sync = () => { if (document.activeElement !== input) input.value = opts[f.key] || ""; };
  } else if (f.type === "timeEntity") {
    const box = timeEntityControls(id, () => opts[f.key], (v) => { if (v) opts[f.key] = v; else delete opts[f.key]; }, f.slug, f.fallback);
    wrap.append(h("label", { for: id, text: f.label }), help, box);
    wrap.sync = box.sync;
  } else if (f.type === "stateEntity") {
    const kind = select([["", "Nothing"], ["sim", "A stand-in entity"]], { id, ...described });
    const startId = nextId();
    const start = f.text ? h("input", { type: "text", id: startId, spellcheck: "false" }) : select(ON_OFF, { id: startId });
    const note = h("p", { class: "help mono-id" });
    const startWrap = h("div", { class: "entity-time" }, h("label", { for: startId, text: f.startLabel }), start);
    kind.addEventListener("change", () => {
      if (kind.value) {
        const eid = opts[f.key] || f.fallbackId;
        opts[f.key] = eid;
        if (opts.entities[eid] == null) opts.entities[eid] = "off";
      } else delete opts[f.key];
      changed();
    });
    start.addEventListener(f.text ? "input" : "change", () => { if (opts[f.key]) { opts.entities[opts[f.key]] = start.value; changed(); } });
    wrap.append(h("label", { for: id, text: f.label }), help, h("div", { class: "entity" }, kind, startWrap, note));
    wrap.sync = () => {
      const eid = opts[f.key];
      kind.value = eid ? "sim" : "";
      startWrap.hidden = note.hidden = !eid;
      if (eid) {
        if (document.activeElement !== start) start.value = opts.entities[eid] ?? "off";
        note.textContent = `Stands in for ${eid}.`;
      }
    };
  } else if (f.type === "anchor") {
    const time = h("input", { type: "time", id: `${id}-t` });
    const ramp = h("input", { type: "number", id: `${id}-r`, min: 0, max: 480, step: 5, inputmode: "numeric" });
    const a = () => opts[f.anchor];
    time.addEventListener("change", () => { if (time.value) { a().time = time.value; changed(); } });
    ramp.addEventListener("input", () => {
      const v = Number(ramp.value);
      if (ramp.value !== "" && v >= 0 && v <= 480) { a().ramp = Math.round(v); changed(); }
    });
    const ent = timeEntityControls(`${id}-e`, () => a().entity, (v) => { if (v) a().entity = v; else delete a().entity; },
      f.anchor, anchorTime(f.anchor));
    wrap.append(
      h("h3", { text: f.label }), help,
      h("label", { for: `${id}-e`, text: "Use a time from" }), ent,
      h("div", { class: "anchor" },
        h("div", {}, h("label", { for: `${id}-t`, text: "Time" }), time),
        h("div", {}, h("label", { for: `${id}-r`, text: "Change over (min)" }), ramp)),
      h("p", { class: "help", text: "Time is used when nothing is picked above. Change over: how long the change takes, centred on the time. 0 changes it straight away." }),
    );
    wrap.sync = () => { ent.sync(); time.value = a().time; if (document.activeElement !== ramp) ramp.value = a().ramp; };
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
  buildSimForm();
}

// ---- the speaker panel: start of the day, examples and the day's events ---------------------
function buildSimForm() {
  const form = document.getElementById("sim-fields");

  const picks = h("div", { class: "picks" });
  for (const ex of EXAMPLES) {
    picks.append(h("button", { type: "button", text: ex.name, onclick: () => {
      opts.sim = exampleSim(ex);
      // An example that needs a skipped input adds it, so it shows something.
      const skip = String(opts.skip_sources || "").split(",").map((x) => x.trim().toLowerCase());
      if (ex.skip && !skip.includes(ex.skip.toLowerCase())) opts.skip_sources = [opts.skip_sources, ex.skip].filter((x) => String(x || "").trim()).join(", ");
      simCursor = null;
      changed();
    } }));
  }


  const evSec = h("section", {}, h("h2", { text: "During the day" }));
  evSec.append(h("p", { class: "help", text: "The day repeats: the speaker starts each day at the volume, and in the state, it ended the day before. To start the day differently, add something at 00:00. The Adjust while playing and Night cap switches are those settings on the left." }));
  const list = h("ol", { class: "events plain" });
  const add = h("button", { type: "button", class: "small", text: "Add something that happens" });
  add.addEventListener("click", () => {
    const ev = opts.sim.events;
    const last = ev.length ? Math.max(...ev.map((e) => toMin(e.at) ?? 0)) : 11 * 60 + 30;
    ev.push({ at: clockText(Math.min(1439, last + 30)), do: "play", value: null });
    changed();
  });
  evSec.append(list, add);
  form.append(evSec);
  form.append(h("section", {}, h("h2", { text: "Examples" }),
    h("p", { class: "help", text: "Each one replaces the day above and leaves your settings alone, except Turntable, which adds Line In to the inputs to leave alone." }), picks));
  syncs.push(() => renderEvents(list));
}
const toMin = (v) => { const m = /^(\d{1,2}):(\d{2})/.exec(v || ""); return m ? Number(m[1]) * 60 + Number(m[2]) : null; };

let eventsKey = ["", ""];
function renderEvents(list) {
  // Rebuild only when the list or the kinds on offer change, so typing doesn't lose focus.
  const kinds = entityKinds(opts);
  const full = JSON.stringify([kinds, opts.sim.events]);
  const shape = JSON.stringify([opts.sim.events.length, kinds, opts.sim.events.map((e) => [e.do, e.value && e.value.id])]);
  if (full === eventsKey[0]) return;
  const typing = list.contains(document.activeElement) && shape === eventsKey[1];
  eventsKey = [full, shape];
  if (typing) return; // the inputs already show what was typed
  list.textContent = "";
  if (!opts.sim.events.length) list.append(h("li", { class: "muted", text: "Nothing happens yet. Add something, or pick an example." }));
  opts.sim.events.forEach((e, i) => {
    const time = h("input", { type: "time", value: hhmm(e.at), "aria-label": "When" });
    time.addEventListener("change", () => { if (time.value) { e.at = time.value; changed(); } });
    const opts2 = [...EVENT_KINDS, ...kinds.map((k) => [`entity:${k.id}`, k.label])];
    const cur = e.do === "entity" ? `entity:${e.value && e.value.id}` : e.do;
    if (!opts2.some(([v]) => v === cur)) opts2.push([cur, `${e.value && e.value.id} (no longer linked) changes`]);
    const what = select(opts2, { "aria-label": "What happens" });
    what.value = cur;
    what.addEventListener("change", () => {
      const v = what.value;
      if (v.startsWith("entity:")) {
        const k = kinds.find((x) => `entity:${x.id}` === v);
        e.do = "entity";
        e.value = { id: v.slice(7), state: k && k.value === "time" ? "12:00" : "on" };
      } else {
        e.do = v;
        e.value = { volume: 50, source: "Line In", enabled: true, quiet: true, adapt: true, cap: true }[v] ?? null;
      }
      changed();
    });
    let value = null;
    const onoff = (get, put) => {
      const s = select(ON_OFF, { "aria-label": "On or off" });
      s.value = get() ? "on" : "off";
      s.addEventListener("change", () => { put(s.value === "on"); changed(); });
      return s;
    };
    if (e.do === "volume") {
      value = h("input", { type: "number", min: 0, max: 100, step: 1, value: e.value ?? 50, "aria-label": "Volume (%)", class: "pct" });
      value.addEventListener("input", () => { const v = Number(value.value); if (value.value !== "" && v >= 0 && v <= 100) { e.value = v; changed(); } });
    } else if (e.do === "source") {
      value = h("input", { type: "text", value: e.value ?? "", "aria-label": "Input", spellcheck: "false" });
      value.addEventListener("input", () => { e.value = value.value; changed(); });
    } else if (["enabled", "quiet", "adapt", "cap"].includes(e.do)) {
      value = onoff(() => e.value, (v) => { e.value = v; });
    } else if (e.do === "entity") {
      const k = kinds.find((x) => x.id === (e.value && e.value.id));
      if (k && k.value === "onoff") {
        value = select(ON_OFF, { "aria-label": "State" });
        value.value = e.value.state === "on" ? "on" : "off";
        value.addEventListener("change", () => { e.value.state = value.value; changed(); });
      } else if (k && k.value === "time") {
        value = h("input", { type: "time", value: hhmm(e.value.state), "aria-label": "Time" });
        value.addEventListener("change", () => { if (value.value) { e.value.state = value.value; changed(); } });
      } else {
        value = h("input", { type: "text", value: (e.value && e.value.state) ?? "", "aria-label": "State", spellcheck: "false" });
        value.addEventListener("input", () => { e.value.state = value.value; changed(); });
      }
    }
    const remove = h("button", { type: "button", class: "small ghost", text: "Remove", "aria-label": `Remove event ${i + 1}` });
    remove.addEventListener("click", () => { opts.sim.events.splice(i, 1); changed(); });
    list.append(h("li", {}, time, what, value || h("span"), remove));
  });
}

// ---- the charts ------------------------------------------------------------------------------
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
// The frame both charts share: size, scales, gridlines and axis labels.
function frame(box, top, id, label) {
  const W = Math.max(300, Math.round(box.clientWidth));
  const H = Math.round(Math.min(300, Math.max(190, W * 0.42)));
  const L = 40, R = 14, T = 22, B = 26;
  const x = (m) => L + ((W - L - R) * m) / 1440;
  const y = (v) => T + (H - T - B) * (1 - v / top);
  const root = svg("svg", { id, class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H, tabindex: 0, role: "img", "aria-label": label });
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
  return { W, H, L, R, T, B, x, y, root };
}
// Pointer and arrow keys move a cursor; `move(minute or null)` is told where.
function track(g, move, current) {
  const { root, W, L, R } = g;
  const pick = (ev) => {
    const r = root.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    move(Math.max(0, Math.min(1439, Math.round(((px - L) / (W - L - R)) * 1440))));
  };
  root.addEventListener("pointermove", pick);
  root.addEventListener("pointerdown", pick);
  root.addEventListener("pointerleave", (ev) => { if (ev.pointerType === "mouse") move(null); });
  root.addEventListener("keydown", (ev) => {
    const d = { ArrowRight: 15, ArrowLeft: -15, PageUp: 60, PageDown: -60 }[ev.key];
    if (!d) return;
    ev.preventDefault();
    move((((current() ?? nowMinute()) + d) % 1440 + 1440) % 1440);
  });
}
const topFor = (...vals) => Math.min(100, Math.ceil((Math.max(10, ...vals) + 10) / 10) * 10);

let geom = null;
function draw() {
  const box = document.getElementById("chart-box");
  box.textContent = "";
  if (!result) return;
  const s = result.samples;
  const capV = result.cap ? result.cap_volume : 0;
  const g = frame(box, topFor(...s, capV, result.quiet), "chart",
    "The volume your speakers would start at through the day. Use the arrow keys to read it.");
  const { root, x, y, T, H, B, W, R, L } = g;
  geom = g;
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
    const when = opts.cap_enabled ? "" : " when on";
    svg("text", { class: "cap", x: (x(a) + x(b)) / 2, y: yc - 5, "text-anchor": "middle" }, root).textContent = `night cap ${Math.round(result.cap_volume)}%${when}`;
  }
  const yq = y(result.quiet);
  svg("line", { class: "quietline", x1: L, x2: W - R, y1: yq, y2: yq }, root);
  if (s.length) {
    const pts = s.map((v, i) => `${x(i * STEP).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    svg("polyline", { class: "curve", points: pts }, root);
  }
  g.cursor = svg("line", { class: "cursor", y1: T, y2: H - B }, root);
  g.dot = svg("circle", { class: "dot", r: 5 }, root);
  track(g, (m) => { cursor = m; readout(); }, () => cursor);
  box.append(root);
  readout();
}
function inCap(m) {
  return result.cap && spans(result.cap[0], result.cap[1]).some(([a, b]) => m >= a && m < b);
}
const sampleAt = (m) => result.samples[Math.min(result.samples.length - 1, Math.round(m / STEP))];
function readout() {
  const out = document.getElementById("readout");
  if (!result || !result.samples.length || !geom) { out.textContent = ""; return; }
  const m = cursor ?? nowMinute();
  const v = sampleAt(m);
  const { x, y } = geom;
  geom.cursor.setAttribute("x1", x(m)); geom.cursor.setAttribute("x2", x(m));
  geom.dot.setAttribute("cx", x(m)); geom.dot.setAttribute("cy", y(v));
  let text = `${clockText(m)}${cursor == null ? " (now)" : ""}: starts at ${Math.round(v)}%`;
  if (inCap(m) && v > result.cap_volume) text += `, held to ${Math.round(result.cap_volume)}% by the night cap${opts.cap_enabled ? "" : " when on"}`;
  out.textContent = text;
}

// The speaker's day: its volume (a step line), the scheduled volume behind it, playing time shaded.
let simGeom = null;
const levelAt = (trace, sec) => {
  let v = trace[0][1];
  for (const [t, lvl] of trace) { if (t > sec) break; v = lvl; }
  return v;
};
const playingAt = (sim, sec) => sim.playing.some(([a, b]) => sec >= a && sec < b);
function drawSim() {
  const box = document.getElementById("sim-box");
  box.textContent = "";
  const sim = result && result.sim;
  if (!sim) {
    box.append(h("p", { class: "chart-msg", text: result && result.error ? "Fix the schedule to see the speaker's day." : "" }));
    return;
  }
  const g = frame(box, topFor(...sim.trace.map((p) => p[1]), ...result.samples, sim.cap.length ? sim.cap_volume : 0), "sim-chart",
    "The speaker's volume through the simulated day. Use the arrow keys to read it.");
  const { root, x, y, T, H, B } = g;
  simGeom = g;
  for (const [a, b] of sim.playing)
    svg("rect", { class: "playband", x: x(a / 60), y: T, width: Math.max(1, x(b / 60) - x(a / 60)), height: H - T - B }, root);
  if (sim.cap.length) {
    const yc = y(sim.cap_volume);
    for (const [a, b] of sim.cap) {
      svg("rect", { class: "capband", x: x(a), y: T, width: x(b) - x(a), height: yc - T }, root);
      svg("line", { class: "capline", x1: x(a), x2: x(b), y1: yc, y2: yc }, root);
    }
    const [a, b] = sim.cap.reduce((p, q) => (q[1] - q[0] > p[1] - p[0] ? q : p));
    svg("text", { class: "cap", x: (x(a) + x(b)) / 2, y: yc - 5, "text-anchor": "middle" }, root).textContent = `night cap ${Math.round(sim.cap_volume)}%`;
  }
  if (result.samples.length) {
    const pts = result.samples.map((v, i) => `${x(i * STEP).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    svg("polyline", { class: "schedline", points: pts }, root);
  }
  let d = "";
  sim.trace.forEach(([t, v], i) => {
    const px = x(t / 60).toFixed(1), py = y(v).toFixed(1);
    d += i === 0 ? `M${px},${py}` : `H${px}V${py}`;
  });
  svg("path", { class: "speaker", d }, root);
  for (const e of opts.sim.events) {
    const m = toMin(e.at);
    if (m == null) continue;
    svg("line", { class: "evtick", x1: x(m), x2: x(m), y1: H - B - 6, y2: H - B }, root);
  }
  g.cursor = svg("line", { class: "cursor", y1: T, y2: H - B }, root);
  g.dot = svg("circle", { class: "dot speakerdot", r: 5 }, root);
  track(g, (m) => { simCursor = m; simReadout(); }, () => simCursor);
  box.append(root);
  simReadout();

  const log = document.getElementById("sim-log");
  log.textContent = "";
  if (!sim.log.length) log.append(h("li", { class: "muted", text: "Adaptive Audio doesn't change the volume on this day." }));
  for (const line of sim.log) log.append(h("li", {}, h("span", { class: "num", text: line.at }), h("span", { class: "grow", text: line.text })));
}
function simReadout() {
  const out = document.getElementById("sim-readout");
  const sim = result && result.sim;
  if (!sim || !simGeom) { out.textContent = ""; return; }
  const m = simCursor ?? 12 * 60;
  const sec = m * 60 + 59;
  const v = levelAt(sim.trace, sec);
  const { x, y } = simGeom;
  simGeom.cursor.setAttribute("x1", x(m)); simGeom.cursor.setAttribute("x2", x(m));
  simGeom.dot.setAttribute("cx", x(m)); simGeom.dot.setAttribute("cy", y(v));
  const state = playingAt(sim, sec) ? "playing" : "stopped";
  out.textContent = `${clockText(m)}: ${state} at ${Math.round(v)}%, scheduled ${Math.round(sampleAt(m))}%`;
}

// ---- updates ---------------------------------------------------------------------------------
let pending = null;
function changed() {
  for (const f of syncs) f();
  for (const [el, show] of shown) el.hidden = !show(opts);
  history.replaceState(null, "", `${location.pathname}${location.search}#${toHash(opts)}`);
  // Work it out on the next frame, so a slider drag or fast typing runs it once per frame.
  if (pending) return;
  pending = requestAnimationFrame(() => { pending = null; recompute(); });
}
function recompute() {
  try {
    result = JSON.parse(compute(JSON.stringify(opts)));
  } catch (e) {
    result = { error: String(e), samples: [], marks: [], quiet: 0, sim: null };
  }
  const err = document.getElementById("error");
  err.hidden = !result.error;
  err.textContent = result.error ? `This schedule doesn't work: ${result.error}` : "";
  const legend = document.getElementById("legend");
  legend.hidden = !!result.error;
  legend.querySelector('[data-k="band"]').hidden = !result.marks.some((m) => m.ramp);
  legend.querySelector('[data-k="cap"]').hidden = !result.cap;
  document.getElementById("sim-legend").hidden = !result.sim;
  document.querySelector('#sim-legend [data-k="cap"]').hidden = !(result.sim && result.sim.cap.length);
  if (result.error) {
    document.getElementById("chart-box").replaceChildren(h("p", { class: "chart-msg", text: "Fix the schedule to see the chart." }));
    document.getElementById("readout").textContent = "";
  } else draw();
  drawSim();
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
const redraw = () => { if (result && !result.error) draw(); drawSim(); };
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
  if (result) redraw(); // the chart's font size can change with the style
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
document.getElementById("reset").addEventListener("click", () => { opts = startingOptions({}); cursor = simCursor = null; changed(); });
let resizeTimer = null;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (result) redraw(); }, 100); });
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
