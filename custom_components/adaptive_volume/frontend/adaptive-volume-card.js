/*
 * Adaptive Volume card. Dependency-free (no Lit, no build step): a custom element + inline SVG.
 *
 *   type: custom:adaptive-volume-card
 *   entity: sensor.adaptive_volume_living_room_target_volume
 *   title: Living room          # optional
 *   show_history: true          # optional: today's actual speaker volumes as dots
 *
 * Plots the instance's 24 h curve (the sensor's `curve` attribute), a now marker, the cap
 * hours and the quiet level, and each speaker's volume today from the recorder history.
 * Colours come from the HA theme, so it follows light and dark.
 */

const NS = "http://www.w3.org/2000/svg";
const W = 640, H = 250, L = 38, R = 12, T = 34, B = 28;
const PLAYER_COLOURS = ["#ff9800", "#4caf50", "#e91e63", "#9c27b0", "#00bcd4"];
const HISTORY_REFRESH_MS = 5 * 60 * 1000;

const el = (tag, attrs = {}, parent) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
};
// Minutes after midnight in HA's time zone (the curve is in HA's local time, not the viewer's).
const _fmt = {};
function haMinutes(date, tz) {
  const key = tz || "";
  _fmt[key] = _fmt[key] || new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23", ...(tz ? { timeZone: tz } : {}) });
  const [h, m, s] = _fmt[key].format(date).split(":").map(Number);
  return h * 60 + m + s / 60;
}
const hhmm = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(Math.round(m % 60)).padStart(2, "0")}`;

class AdaptiveVolumeCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("Set `entity` to an Adaptive Volume target-volume sensor");
    this._config = { show_history: true, ...config };
    this._history = {};
    this._historyAt = 0;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `
        <style>
          ha-card { padding: 12px 16px 10px; }
          .head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
          .title { font-size: 1.1em; font-weight: 500; color: var(--primary-text-color); }
          .now { color: var(--secondary-text-color); font-size: .9em; }
          .now b { color: var(--primary-text-color); font-size: 1.25em; font-weight: 500; }
          .chips { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0 2px; }
          .chip { font-size: .75em; padding: 2px 8px; border-radius: 10px; background: var(--secondary-background-color);
                  color: var(--secondary-text-color); }
          .chip.on { background: var(--primary-color); color: var(--text-primary-color, #fff); }
          .chip.warn { background: var(--error-color, #db4437); color: #fff; }
          svg { width: 100%; height: auto; display: block; font-family: var(--paper-font-body1_-_font-family, sans-serif); }
          .legend { display: flex; gap: 12px; flex-wrap: wrap; font-size: .8em; color: var(--secondary-text-color); margin-top: 2px; }
          .legend span::before { content: ""; display: inline-block; width: 9px; height: 9px; border-radius: 50%;
                                 background: var(--c); margin-right: 5px; vertical-align: -1px; }
          .legend .curve::before { border-radius: 2px; height: 3px; vertical-align: 2px; width: 14px; }
          .err { color: var(--error-color, #db4437); font-size: .85em; }
        </style>
        <ha-card>
          <div class="head"><div class="title"></div><div class="now"></div></div>
          <div class="chips"></div>
          <div class="plot"></div>
          <div class="legend"></div>
          <div class="err"></div>
        </ha-card>`;
    }
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    if (!st) {
      this.shadowRoot.querySelector(".err").textContent = `${this._config.entity} not found`;
      return;
    }
    // Redraw only when something the card shows has changed (hass updates constantly).
    const players = st.attributes.players || [];
    const key = JSON.stringify([st.state, st.last_updated, players.map((p) => hass.states[p]?.attributes?.volume_level),
                                Math.floor(Date.now() / 60000)]);
    if (key !== this._key) {
      this._key = key;
      this._render(st);
    }
    if (this._config.show_history && Date.now() - this._historyAt > HISTORY_REFRESH_MS) {
      this._historyAt = Date.now();
      this._loadHistory(players);
    }
  }

  async _loadHistory(players) {
    if (!players.length) return;
    const tz = this._hass.config?.time_zone;
    const now = new Date();
    const start = new Date(now.getTime() - haMinutes(now, tz) * 60000);
    try {
      const res = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: start.toISOString(),
        entity_ids: players,
        minimal_response: false,
        no_attributes: false,
        significant_changes_only: false,
      });
      const out = {};
      for (const [pid, states] of Object.entries(res || {})) {
        out[pid] = [];
        let last = null;
        for (const s of states) {
          const v = s.a?.volume_level;
          if (typeof v !== "number" || v === last) continue;
          last = v;
          out[pid].push([haMinutes(new Date((s.lu ?? s.lc) * 1000), tz), v * 100, s.s]);
        }
      }
      this._history = out;
      this._key = null;
      if (this._hass) this.hass = this._hass;
    } catch (e) {
      console.warn("adaptive-volume-card: history unavailable", e);
    }
  }

  _render(st) {
    const a = st.attributes;
    const root = this.shadowRoot;
    const name = this._config.title || (a.friendly_name || "").replace(/ Target volume$/, "").replace(/^Adaptive Volume /, "");
    root.querySelector(".title").textContent = name;
    root.querySelector(".now").innerHTML =
      st.state === "unavailable" || st.state === "unknown" ? "" :
      `now <b>${st.state}%</b>${a.start_volume != null && String(a.start_volume) !== st.state ? ` · starts at ${a.start_volume}%` : ""}`;
    const chips = [
      [a.enabled ? "On" : "Off", a.enabled ? "on" : ""],
      [{ sigmoid: "Sigmoid", linear: "Linear", steps: "Steps" }[a.curve_type] || a.curve_type, ""],
      a.adapt ? ["Adapting while playing", "on"] : null,
      a.quiet_active ? [`Quiet ${a.quiet_volume}%`, "on"] : null,
      a.cap_active && !a.quiet_active ? [`Capped ${a.cap}%`, "on"] : null,
      (a.taken_over || []).length ? [`Hand-set: ${a.taken_over.map((p) => this._name(p)).join(", ")}`, ""] : null,
      a.schedule_error ? [a.schedule_error, "warn"] : null,
    ].filter(Boolean);
    root.querySelector(".chips").innerHTML = chips.map(([t, c]) => `<span class="chip ${c}">${t}</span>`).join("");
    root.querySelector(".err").textContent = "";

    const curve = a.curve || [];
    const step = a.curve_step || 10;
    const players = a.players || [];
    const hist = this._config.show_history ? this._history : {};
    const live = players.map((p) => (this._hass.states[p]?.attributes?.volume_level ?? null));
    const allVals = [...curve, a.cap_volume || 0, a.quiet_active ? a.quiet_volume : 0,
                     ...Object.values(hist).flat().map((p) => p[1]), ...live.filter((v) => v != null).map((v) => v * 100)];
    const top = Math.min(100, Math.ceil((Math.max(10, ...allVals) + 8) / 10) * 10);
    const x = (m) => L + ((W - L - R) * m) / 1440;
    const y = (v) => T + (H - T - B) * (1 - v / top);

    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${name} volume through the day` });
    const grid = "var(--divider-color, #8884)";
    const text = "var(--secondary-text-color)";
    const gstep = top <= 50 ? 10 : 20;
    for (let v = 0; v <= top; v += gstep) {
      el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: grid, "stroke-width": 0.6 }, svg);
      el("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end", fill: text, "font-size": 10 }, svg).textContent = `${v}%`;
    }
    for (let h = 0; h <= 24; h += 3) {
      el("line", { x1: x(h * 60), x2: x(h * 60), y1: T, y2: H - B, stroke: grid, "stroke-width": 0.6 }, svg);
      el("text", { x: x(h * 60), y: H - B + 15, "text-anchor": h === 0 ? "start" : h === 24 ? "end" : "middle", fill: text, "font-size": 10 }, svg).textContent = `${String(h).padStart(2, "0")}:00`;
    }
    // Ramps and anchor names; a label close to the previous one drops to a second row.
    let lastLabel = -1e9, row = 0;
    for (const m of [...(a.marks || [])].sort((p, q) => p.at - q.at)) {
      if (m.ramp) {
        const s = m.at - (a.curve_type === "steps" ? 0 : m.ramp / 2);
        el("rect", { x: x(s), y: T, width: x(m.ramp) - L, height: H - T - B, fill: "var(--primary-color)", "fill-opacity": 0.07 }, svg);
      }
      if (m.name) {
        row = m.at - lastLabel < 170 ? 1 - row : 0;
        lastLabel = m.at;
        el("text", { x: x(m.at), y: T - 6 - row * 12, "text-anchor": "middle", fill: text, "font-size": 10 }, svg).textContent =
          `${m.name[0].toUpperCase()}${m.name.slice(1)} ${hhmm(m.at)}`;
      }
    }
    // Cap hours: shade above the cap line.
    if (a.cap_window && a.cap_volume != null) {
      const [s, e] = a.cap_window;
      const spans = s === e ? [[0, 1440]] : s < e ? [[s, e]] : [[s, 1440], [0, e]];
      for (const [p, q] of spans) {
        el("rect", { x: x(p), y: T, width: x(q) - x(p), height: y(a.cap_volume) - T, fill: "var(--error-color, #db4437)", "fill-opacity": 0.1 }, svg);
        el("line", { x1: x(p), x2: x(q), y1: y(a.cap_volume), y2: y(a.cap_volume), stroke: "var(--error-color, #db4437)", "stroke-width": 1.2, "stroke-dasharray": "4 3" }, svg);
      }
    }
    if (a.quiet_active && a.quiet_volume != null) {
      el("line", { x1: L, x2: W - R, y1: y(a.quiet_volume), y2: y(a.quiet_volume), stroke: "var(--primary-color)", "stroke-width": 1.2, "stroke-dasharray": "2 3" }, svg);
    }
    // The curve.
    if (curve.length) {
      el("polyline", {
        points: curve.map((v, i) => `${x(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(" "),
        fill: "none", stroke: "var(--primary-color)", "stroke-width": 2.5, "stroke-linejoin": "round",
      }, svg);
    }
    // Today's actual volumes.
    players.forEach((p, i) => {
      const c = PLAYER_COLOURS[i % PLAYER_COLOURS.length];
      for (const [m, v, s] of hist[p] || []) {
        el("circle", { cx: x(m), cy: y(v), r: s === "playing" ? 2.6 : 1.8, fill: c, "fill-opacity": s === "playing" ? 0.85 : 0.35 }, svg);
      }
    });
    // Now.
    const nowM = haMinutes(new Date(), this._hass.config?.time_zone);
    el("line", { x1: x(nowM), x2: x(nowM), y1: T, y2: H - B, stroke: text, "stroke-width": 1 }, svg);
    if (curve.length) {
      const v = curve[Math.min(curve.length - 1, Math.round(nowM / step))];
      el("circle", { cx: x(nowM), cy: y(v), r: 4.5, fill: "var(--primary-color)", stroke: "var(--card-background-color, #fff)", "stroke-width": 1.5 }, svg);
    }
    players.forEach((p, i) => {
      if (live[i] == null) return;
      const playing = this._hass.states[p]?.state === "playing";
      el("circle", { cx: x(nowM), cy: y(live[i] * 100), r: 4, fill: playing ? PLAYER_COLOURS[i % PLAYER_COLOURS.length] : "none",
                     stroke: PLAYER_COLOURS[i % PLAYER_COLOURS.length], "stroke-width": 1.5 }, svg);
    });
    const plot = root.querySelector(".plot");
    plot.replaceChildren(svg);

    root.querySelector(".legend").innerHTML =
      `<span class="curve" style="--c: var(--primary-color)">Schedule</span>` +
      players.map((p, i) => {
        const v = live[i];
        return `<span style="--c:${PLAYER_COLOURS[i % PLAYER_COLOURS.length]}">${this._name(p)}${v != null ? ` ${Math.round(v * 100)}%` : ""}</span>`;
      }).join("");
  }

  _name(pid) {
    return this._hass?.states[pid]?.attributes?.friendly_name || pid;
  }

  getCardSize() {
    return 5;
  }

  static getStubConfig(hass) {
    const e = Object.keys(hass.states).find((k) => k.startsWith("sensor.adaptive_volume_") && k.endsWith("_target_volume"));
    return { entity: e || "" };
  }
}

customElements.define("adaptive-volume-card", AdaptiveVolumeCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "adaptive-volume-card",
  name: "Adaptive Volume",
  description: "The volume schedule through the day, with each speaker's actual volume.",
});
