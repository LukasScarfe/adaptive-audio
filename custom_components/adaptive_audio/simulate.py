"""A day of one speaker under Adaptive Audio, worked out without Home Assistant. The online
tester runs it in the browser (Pyodide). It follows the rules in the controller.py docstring
step for step; tests/test_simulate.py runs the same scenarios through the real controller and
fails if the two disagree, so change both together.

    run(options, rise, set_, entities, start, events, days=1) -> {"trace", "playing", "cap", "log", "sets"}

With days > 1 the same events happen every day and only the last day is returned, so the day
loops: it starts exactly as the day before ended (volume, playing, switches, a ramp under way).

`entities` holds the simulated entities: id -> state. A time entity's state is "HH:MM"; the
quiet and night cap entities have any text state ("on", "off", ...).
`start` is the speaker and switches at 00:00: playing, volume (%), source, enabled, quiet.
Adjust while playing and Night cap are options (`adapt`, `cap_enabled`); the `adapt` and `cap`
events change them during the day. Each event is {"at": "HH:MM", "do": kind, "value": ...}. Kinds:
    play, stop                 the speaker starts or stops playing
    volume   <percent>         someone changes the volume by hand (or another app does)
    source   <text>            the speaker switches input
    enabled / quiet / adapt / cap   <bool>   the instance's switches (cap = Night cap)
    entity   {"id", "state"}   a simulated entity changes state
    apply                      the Set volume now button
"""

from __future__ import annotations

import heapq
from typing import Any

from . import curve, schedule
from .const import (
    CONF_ADAPT,
    CONF_AUTORESET,
    CONF_CAP_ENABLED,
    CONF_CAP_ENTITY,
    CONF_CAP_VOLUME,
    CONF_IDLE_GAP,
    CONF_MAX_RATE,
    CONF_QUIET_ENTITY,
    CONF_QUIET_INSTANT,
    CONF_QUIET_STATE,
    CONF_QUIET_VOLUME,
    CONF_SKIP_SOURCES,
)

TOLERANCE = 0.015  # the controller's _TOLERANCE
TICK_OFFSET = 30  # seconds past each minute the 1-minute tick fires
DAY_SECONDS = 1440 * 60

REASONS = {  # why a volume was set, in the tester's words
    "start": "started playing",
    "adapt": "adjusting while playing",
    "quiet": "quiet mode",
    "cap": "night cap",
    "quiet off": "quiet mode off",
    "manual": "Set volume now",
}


def clock(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60 % 24:02d}:{m % 60:02d}"


def entity_minute_from(entities: dict[str, Any]):
    """Minutes after midnight a simulated time entity holds, or None."""

    def look(eid: str) -> int | None:
        v = entities.get(eid)
        if not isinstance(v, str) or ":" not in v:
            return None
        try:
            return schedule.parse_clock(v) % schedule.DAY
        except (ValueError, IndexError):
            return None

    return look


class Sim:
    def __init__(self, options, rise, set_, entities, start) -> None:
        self.o = dict(options)
        self.rise, self.set_ = rise, set_
        self.entities = dict(entities or {})
        start = start or {}
        self.t = 0.0  # seconds after midnight
        self.playing = bool(start.get("playing"))
        self.level = round(float(start.get("volume", 50)) / 100, 2)
        self.source = start.get("source") or ""
        self.enabled = bool(start.get("enabled", True))
        self.quiet_switch = bool(start.get("quiet"))
        self.manual_since: float | None = None
        self.expected: float | None = None
        self.stopped_at: float | None = None  # None: stopped "long ago", like a fresh start
        self.ramping: str | None = None  # reason while ramping toward the start volume
        self.ramp_at: float | None = None  # when the ramp task wakes next; None = no task
        self.fn = None
        self.error: str | None = None
        self.trace: list[list[float]] = [[0.0, self.level * 100]]
        self.playing_spans: list[list[float]] = []
        self._play_from = 0.0 if self.playing else None
        self.sets: list[tuple[float, float, str]] = []  # (t, percent, reason)
        self.notes: list[tuple[float, str]] = []
        self.cap_minutes: list[tuple[float, bool]] = []  # (tick time, night cap hours active)
        self._build()
        self.was_quiet = self.quiet_active

    # ---- the controller's properties ----------------------------------------------------

    def opt(self, key):
        return curve.opt(self.o, key)

    @property
    def adapt(self) -> bool:
        return bool(self.opt(CONF_ADAPT))

    def minute(self) -> int:
        return int(self.t // 60) % 1440

    def _build(self) -> None:
        try:
            self.fn, _ = curve.builder(self.o, self.rise, self.set_, entity_minute_from(self.entities))
            self.error = None
        except schedule.ScheduleError as err:
            self.fn, self.error = None, str(err)

    @property
    def skip_sources(self) -> set[str]:
        raw = self.opt(CONF_SKIP_SOURCES) or ""
        return {s.strip().casefold() for s in raw.split(",") if s.strip()}

    @property
    def skipped(self) -> bool:
        return bool(self.source) and self.source.casefold() in self.skip_sources

    @property
    def quiet_active(self) -> bool:
        if self.quiet_switch:
            return True
        if entity := self.opt(CONF_QUIET_ENTITY):
            st = self.entities.get(entity)
            want = str(self.opt(CONF_QUIET_STATE) or "on").strip()
            return st is not None and str(st).casefold() == want.casefold()
        return False

    @property
    def cap_on(self) -> bool:
        if self.opt(CONF_CAP_ENABLED):
            return True
        if entity := self.opt(CONF_CAP_ENTITY):
            return self.entities.get(entity) == "on"
        return False

    @property
    def cap(self) -> float | None:
        if self.quiet_active:
            return float(self.opt(CONF_QUIET_VOLUME))
        if self.cap_on and schedule.in_window(
            self.minute(), *curve.cap_window(self.o, entity_minute_from(self.entities))
        ):
            return float(self.opt(CONF_CAP_VOLUME))
        return None

    @property
    def target(self) -> float | None:
        return None if self.fn is None else self.fn(self.minute())

    @property
    def start_volume(self) -> int | None:
        if self.quiet_active:
            vol = float(self.opt(CONF_QUIET_VOLUME))
        else:
            vol = self.target
            if vol is None:
                return None
        if (cap := self.cap) is not None:
            vol = min(vol, cap)
        return int(round(max(0.0, min(100.0, vol))))

    # ---- acting -------------------------------------------------------------------------

    def _set_volume(self, percent: float, reason: str) -> None:
        level = round(percent / 100, 2)
        self.expected = level
        old = self.level
        self.level = level
        self.trace.append([self.t, level * 100])
        self.sets.append((self.t, level * 100, reason))
        if self.playing and old != level:  # the state change comes back to _on_player
            self._volume_changed()

    def _apply(self, reason: str) -> None:
        if not self.enabled or self.skipped:
            return
        vol = self.start_volume
        if vol is not None:
            self._set_volume(vol, reason)

    def _enforce_cap(self) -> None:
        if not self.enabled or not self.playing or self.skipped:
            return
        cap = self.cap
        if cap is None:
            return
        if self.level * 100 > cap + 0.5:
            self._set_volume(cap, "quiet" if self.quiet_active else "cap")

    def _taken_over(self) -> bool:
        if self.manual_since is None:
            return False
        reset = float(self.opt(CONF_AUTORESET) or 0)
        if reset > 0 and self.t - self.manual_since >= reset * 60:
            self.manual_since = None
            self.notes.append((self.t, "following the schedule again"))
            return False
        return True

    def _adapt(self) -> None:
        goal = self.start_volume
        if goal is None or self.quiet_active or self.ramping:
            return
        if not self.playing or self.skipped or self._taken_over():
            return
        if abs(goal - self.level * 100) >= 1:
            self.ramping = "adapt"
        self._start_ramp()

    def _start_ramp(self) -> None:
        if self.ramping and self.ramp_at is None:
            self._ramp_step()

    def _ramp_step(self) -> None:
        """One pass of the controller's _ramp loop, then its sleep (or the task ends)."""
        self.ramp_at = None
        if not self.ramping:
            return
        goal = self.start_volume
        if not self.enabled or self.quiet_active or goal is None:
            self.ramping = None
            return
        reason = self.ramping
        if not self.playing or self.skipped or self._taken_over() or (reason == "adapt" and not self.adapt):
            self.ramping = None
            return
        level = self.level
        if self.expected is not None and abs(level - self.expected) <= TOLERANCE:
            level = self.expected
        diff = goal - level * 100
        if abs(diff) < 0.5:
            self.ramping = None
            return
        if abs(diff) <= 1:
            self.ramping = None
        self._set_volume(level * 100 + max(-1.0, min(1.0, diff)), reason)
        if self.ramping:
            self.ramp_at = self.t + 60 / max(1.0, float(self.opt(CONF_MAX_RATE)))

    def _leave_quiet(self) -> None:
        if not self.enabled:
            return
        self.manual_since = None
        if self.opt(CONF_QUIET_INSTANT):
            if self.playing:
                self._apply("quiet off")
            return
        self.ramping = "quiet off"
        self._start_ramp()

    # ---- events -------------------------------------------------------------------------

    def _volume_changed(self) -> None:
        """Playing -> playing with a new level: ours, or a hand change. Then the cap check."""
        if self.expected is None or abs(self.level - self.expected) > TOLERANCE:
            if self.manual_since is None:
                self.manual_since = self.t
        self._enforce_cap()

    def _quiet_changed(self) -> None:
        now = self.quiet_active
        if now and not self.was_quiet:
            self.ramping = None
            self._enforce_cap()
        elif self.was_quiet and not now:
            self.was_quiet = now
            self._leave_quiet()
        self.was_quiet = now

    def event(self, kind: str, value: Any) -> None:
        if kind == "play" and not self.playing:
            self.playing = True
            self._play_from = self.t
            gap = float(self.opt(CONF_IDLE_GAP)) * 60
            if self.stopped_at is None or self.t - self.stopped_at >= gap:
                self.manual_since = None
                self._apply("start")
            else:
                self.notes.append((self.t, "playing again after a short pause: volume kept"))
        elif kind == "stop" and self.playing:
            self.playing = False
            self.stopped_at = self.t
            self.playing_spans.append([self._play_from, self.t])
            self._play_from = None
        elif kind == "volume":
            level = round(float(value) / 100, 2)
            if level == self.level:
                return
            self.level = level
            self.trace.append([self.t, level * 100])
            was = self.manual_since
            if self.playing:
                self._volume_changed()
            took = was is None and self.manual_since is not None and self.adapt
            text = f"set to {round(level * 100)}% by hand"
            if not self.playing:
                text += " while stopped"
            elif took:
                text += ": stops following the schedule"
            self.notes.append((self.t, text))
        elif kind == "source":
            self.source = str(value or "")
        elif kind == "enabled":
            self.enabled = bool(value)
        elif kind == "adapt":
            self.o[CONF_ADAPT] = bool(value)
            if value:
                self.manual_since = None
        elif kind == "quiet":
            self.quiet_switch = bool(value)
            self._quiet_changed()
        elif kind == "cap":
            self.o[CONF_CAP_ENABLED] = bool(value)
            self._enforce_cap()
        elif kind == "entity":
            eid, state = value.get("id"), value.get("state")
            if not eid:
                return
            self.entities[eid] = state
            if eid == self.opt(CONF_QUIET_ENTITY):
                self._quiet_changed()
            if eid == self.opt(CONF_CAP_ENTITY):
                self._enforce_cap()
            if eid in curve.time_entities(self.o):
                self._build()
                self._enforce_cap()
        elif kind == "apply":
            self.manual_since = None
            self._apply("manual")

    def tick(self) -> None:
        window = curve.cap_window(self.o, entity_minute_from(self.entities))
        self.cap_minutes.append((self.t, self.cap_on and schedule.in_window(self.minute(), *window)))
        if not self.enabled:
            return
        self._enforce_cap()
        if self.adapt:
            self._adapt()


def run(
    options: dict[str, Any],
    rise: int | None,
    set_: int | None,
    entities: dict[str, Any],
    start: dict[str, Any],
    events: list[dict[str, Any]],
    days: int = 1,
) -> dict[str, Any]:
    sim = Sim(options, rise, set_, entities, start)
    days = max(1, int(days))
    end = DAY_SECONDS * days
    # The queue: (time, order, kind, value). Events at a minute come before its tick.
    queue: list[tuple[float, int, str, Any]] = []
    order = 0
    for day in range(days):
        for ev in events:
            try:
                at = schedule.parse_clock(ev.get("at")) * 60 + day * DAY_SECONDS
            except (ValueError, IndexError, TypeError):
                continue
            heapq.heappush(queue, (float(at), order, ev.get("do"), ev.get("value")))
            order += 1
    for m in range(1440 * days):
        heapq.heappush(queue, (float(m * 60 + TICK_OFFSET), order + m, "_tick", None))
    while queue:
        t, _, kind, value = queue[0]
        if sim.ramp_at is not None and sim.ramp_at <= t:
            sim.t = sim.ramp_at
            sim._ramp_step()
            continue
        heapq.heappop(queue)
        sim.t = t
        if kind == "_tick":
            sim.tick()
        else:
            sim.event(kind, value)
    while sim.ramp_at is not None and sim.ramp_at < end:
        sim.t = sim.ramp_at
        sim._ramp_step()
    if sim._play_from is not None:
        sim.playing_spans.append([sim._play_from, end])
    sim.trace.append([end, sim.level * 100])

    # Keep the last day, as seconds after its midnight.
    off = end - DAY_SECONDS
    before = [p for p in sim.trace if p[0] <= off]
    trace = [[0.0, before[-1][1]]] + [[t - off, v] for t, v in sim.trace if t > off]
    playing = [[max(a, off) - off, b - off] for a, b in sim.playing_spans if b > off]
    sets = [(t - off, v, r) for t, v, r in sim.sets if t >= off]
    notes = [(t - off, text) for t, text in sim.notes if t >= off]
    cap: list[list[float]] = []
    for t, on in sim.cap_minutes:
        if t < off or not on:
            continue
        m = (t - off) // 60
        if cap and cap[-1][1] == m:
            cap[-1][1] = m + 1
        else:
            cap.append([m, m + 1])
    return {
        "trace": trace,
        "playing": playing,
        "cap": cap,  # minutes [from, to) when the night cap held, at cap_volume
        "cap_volume": float(sim.opt(CONF_CAP_VOLUME)),
        "log": _log(sets, notes),
        "sets": [[t, v, r] for t, v, r in sets],
        "error": sim.error,
    }


def _log(sets: list[tuple[float, float, str]], notes: list[tuple[float, str]]) -> list[dict[str, Any]]:
    """The day in plain words. A run of 1 % ramp steps the same way becomes one line."""
    lines: list[tuple[float, str]] = list(notes)
    note_times = sorted(t for t, _ in notes)
    i = 0

    def quiet_between(a: float, b: float) -> bool:
        return not any(a < t <= b for t in note_times)

    while i < len(sets):
        t, v, r = sets[i]
        j = i
        if r in ("adapt", "quiet off"):
            while (
                j + 1 < len(sets)
                and sets[j + 1][2] == r
                and abs(sets[j + 1][1] - sets[j][1]) <= 1.01
                and (j == i or (sets[j + 1][1] - sets[j][1]) * (sets[i + 1][1] - sets[i][1]) > 0)
                and sets[j + 1][0] - sets[j][0] <= 30 * 60
                and quiet_between(sets[j][0], sets[j + 1][0])
            ):
                j += 1
        if j > i:
            start = sets[i][1] - (sets[i + 1][1] - sets[i][1])  # the level before the first step
            lines.append((t, f"{REASONS[r]}: {round(start)}% to {round(sets[j][1])}% by {clock(sets[j][0])}"))
        else:
            lines.append((t, f"{REASONS.get(r, r)}: set to {round(v)}%"))
        i = j + 1
    lines.sort(key=lambda x: x[0])
    return [{"at": clock(t), "t": t, "text": text} for t, text in lines]
