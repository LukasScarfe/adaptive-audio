"""The per-instance controller: watches the players and sets their volume.

Rules:
- A player that starts playing after `idle_gap` minutes of not playing gets the start volume:
  the quiet volume while quiet is active, else the schedule's target, never above the cap.
- With "Adapt while playing" on, every minute a playing player that is off that volume starts
  ramping toward it in 1 % steps, `max_rate` steps a minute (10 by default), so it never moves
  faster than `max_rate` % a minute and never jumps. Starts, quiet mode and the night cap still apply at once. A hand change (any volume change Adaptive Audio didn't make) stops
  adapting that player until its next fresh start, or for `autoreset` minutes if that is set.
- With it off, the volume is left alone mid-play.
- The night cap is on while its switch (the `cap_enabled` option) or its linked entity is on, and
  then applies during cap hours (clock times, or time entities such as a time helper).
- Either way, a raise above the cap is pulled back to the cap (during cap hours, or at any time
  while quiet is active, when the cap is the quiet volume). Turning quiet on pulls playing
  players down to the quiet volume.
- Turning quiet off brings playing players back up to the start volume: at once with
  `quiet_instant`, else by the same 1 % ramp at `max_rate` % a minute. This happens whether or not adapting
  is on, and clears any hand-change takeover.
- Anchors and cap hours can follow time entities; a change to one rebuilds the schedule.
- A player whose source is in `skip_sources` (e.g. the turntable's Line In) is never touched.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_VOLUME_LEVEL,
    DOMAIN as MP_DOMAIN,
    SERVICE_VOLUME_SET,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from . import curve, schedule
from .const import (
    CONF_AUTORESET,
    CONF_CAP_ENABLED,
    CONF_CAP_ENTITY,
    CONF_CAP_VOLUME,
    CONF_IDLE_GAP,
    CONF_MAX_RATE,
    CONF_PLAYERS,
    CONF_QUIET_ENTITY,
    CONF_QUIET_INSTANT,
    CONF_QUIET_STATE,
    CONF_QUIET_VOLUME,
    CONF_SKIP_SOURCES,
)

_LOGGER = logging.getLogger(__name__)
_TOLERANCE = 0.015  # volume levels this close count as "the one we set"


def sun_minutes(hass: HomeAssistant, day: date) -> tuple[int | None, int | None]:
    """Local sunrise and sunset (minutes after midnight) for a date."""
    out = []
    for event in (SUN_EVENT_SUNRISE, SUN_EVENT_SUNSET):
        when = get_astral_event_date(hass, event, day)
        if when is None:
            out.append(None)
        else:
            local = dt_util.as_local(when)
            out.append(local.hour * 60 + local.minute)
    return out[0], out[1]


def entity_minute(hass: HomeAssistant, entity_id: str) -> int | None:
    """Time of day (minutes after midnight, local) a time entity holds: a time helper
    (input_datetime with a time, or a time entity) or a timestamp sensor such as
    sensor.sun_next_rising. None if it has no usable time right now."""
    st = hass.states.get(entity_id)
    if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
        return None
    if st.domain == "input_datetime":
        if not st.attributes.get("has_time", True):
            return None
        h, m = st.attributes.get("hour"), st.attributes.get("minute")
        if isinstance(h, int) and isinstance(m, int):
            return h * 60 + m
    when = dt_util.parse_datetime(st.state)
    if when is not None:
        local = dt_util.as_local(when) if when.tzinfo else when
        return local.hour * 60 + local.minute
    t = dt_util.parse_time(st.state)
    return None if t is None else t.hour * 60 + t.minute


class AdaptiveAudioController:
    """State and behaviour for one Adaptive Audio instance (config entry)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True  # restored by the switches
        self.quiet_switch = False
        self.adapt = False
        self.last_applied: dict[str, dict] = {}
        self.manual: dict[str, datetime] = {}  # players a hand change has taken over
        self._expected: dict[str, float] = {}  # the level we last set per player
        self._stopped_at: dict[str, datetime | None] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._was_quiet = False
        self._ramping: dict[str, str] = {}  # players ramping toward the start volume -> reason
        self._ramp_task: asyncio.Task | None = None
        self._fn_day: date | None = None
        self._fn: Callable[[int], float] | None = None
        self.marks: list[dict[str, Any]] = []
        self.schedule_error: str | None = None
        self._build()

    # ---- options -------------------------------------------------------------------------

    def opt(self, key: str):
        return curve.opt(self.entry.options, key)

    @property
    def players(self) -> list[str]:
        return list(self.opt(CONF_PLAYERS) or [])

    @property
    def skip_sources(self) -> set[str]:
        raw = self.opt(CONF_SKIP_SOURCES) or ""
        return {s.strip().casefold() for s in raw.split(",") if s.strip()}

    # ---- lifecycle -----------------------------------------------------------------------

    @callback
    def async_start(self) -> None:
        for pid in self.players:
            st = self.hass.states.get(pid)
            self._stopped_at[pid] = None if st is None or st.state == STATE_PLAYING else st.last_changed
        self._unsubs.append(async_track_state_change_event(self.hass, self.players, self._on_player))
        if quiet_entity := self.opt(CONF_QUIET_ENTITY):
            self._unsubs.append(
                async_track_state_change_event(self.hass, [quiet_entity], self._on_quiet_entity)
            )
        if cap_entity := self.opt(CONF_CAP_ENTITY):
            self._unsubs.append(
                async_track_state_change_event(self.hass, [cap_entity], self._on_cap_entity)
            )
        if times := curve.time_entities(self.entry.options):
            self._unsubs.append(async_track_state_change_event(self.hass, times, self._on_time_entity))
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, timedelta(minutes=1)))
        self._was_quiet = self.quiet_active

    @callback
    def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()
        self._ramping.clear()
        if self._ramp_task is not None:
            self._ramp_task.cancel()
            self._ramp_task = None

    @callback
    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # ---- the schedule --------------------------------------------------------------------

    def _build(self) -> None:
        """(Re)build today's volume function; sun anchors move daily."""
        today = dt_util.now().date()
        self._fn_day = today
        try:
            rise = set_ = None
            if curve.uses_sun(self.entry.options):
                rise, set_ = sun_minutes(self.hass, today)
            self._fn, self.marks = curve.builder(
                self.entry.options, rise, set_, lambda e: entity_minute(self.hass, e)
            )
            self.schedule_error = None
        except schedule.ScheduleError as err:
            self._fn, self.marks = None, []
            self.schedule_error = str(err)
            _LOGGER.warning("%s: schedule can't be used: %s", self.entry.title, err)

    def _now_minutes(self) -> int:
        now = dt_util.now()
        return now.hour * 60 + now.minute

    @property
    def fn(self) -> Callable[[int], float] | None:
        if self._fn_day != dt_util.now().date():
            self._build()
        return self._fn

    @property
    def target(self) -> float | None:
        fn = self.fn
        return None if fn is None else fn(self._now_minutes())

    def curve_samples(self) -> list[float]:
        fn = self.fn
        return [] if fn is None else curve.samples(fn)

    @property
    def quiet_active(self) -> bool:
        if self.quiet_switch:
            return True
        if entity := self.opt(CONF_QUIET_ENTITY):
            st = self.hass.states.get(entity)
            want = str(self.opt(CONF_QUIET_STATE) or "on").strip()
            return st is not None and st.state.casefold() == want.casefold()
        return False

    @property
    def cap_on(self) -> bool:
        """The night cap is switched on: its own switch, or the linked entity is on."""
        if self.opt(CONF_CAP_ENABLED):
            return True
        if entity := self.opt(CONF_CAP_ENTITY):
            st = self.hass.states.get(entity)
            return st is not None and st.state == "on"
        return False

    def cap_window(self) -> tuple[int, int]:
        return curve.cap_window(self.entry.options, lambda e: entity_minute(self.hass, e))

    @property
    def cap_hours_active(self) -> bool:
        if not self.cap_on:
            return False
        return schedule.in_window(self._now_minutes(), *self.cap_window())

    @property
    def cap(self) -> float | None:
        """The current maximum (percent), or None when nothing caps the volume."""
        if self.quiet_active:
            return float(self.opt(CONF_QUIET_VOLUME))
        if self.cap_hours_active:
            return float(self.opt(CONF_CAP_VOLUME))
        return None

    @property
    def start_volume(self) -> int | None:
        """The volume (percent) a fresh start gets now, and what adapting aims for."""
        if self.quiet_active:
            vol = float(self.opt(CONF_QUIET_VOLUME))
        else:
            vol = self.target
            if vol is None:
                return None
        if (cap := self.cap) is not None:
            vol = min(vol, cap)
        return int(round(max(0.0, min(100.0, vol))))

    # ---- acting --------------------------------------------------------------------------

    def _skipped(self, st: State | None) -> bool:
        if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return True
        source = st.attributes.get(ATTR_INPUT_SOURCE)
        return source is not None and str(source).casefold() in self.skip_sources

    async def _set_volume(self, pid: str, percent: float, reason: str) -> None:
        level = round(percent / 100, 2)
        self._expected[pid] = level
        try:
            await self.hass.services.async_call(
                MP_DOMAIN,
                SERVICE_VOLUME_SET,
                {ATTR_ENTITY_ID: pid, ATTR_MEDIA_VOLUME_LEVEL: level},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001 - a speaker error must not break the others
            _LOGGER.warning("%s: couldn't set %s to %s%%: %s", self.entry.title, pid, percent, err)
            return
        self.last_applied[pid] = {
            "volume": int(round(percent)),
            "reason": reason,
            "at": dt_util.now().isoformat(timespec="seconds"),
        }
        _LOGGER.debug("%s: %s -> %s%% (%s)", self.entry.title, pid, percent, reason)
        self.notify()

    async def async_apply(self, pid: str, reason: str = "start") -> None:
        """Give one player the start volume now."""
        if not self.enabled or self._skipped(self.hass.states.get(pid)):
            return
        vol = self.start_volume
        if vol is not None:
            await self._set_volume(pid, vol, reason)

    async def async_apply_all(self) -> None:
        """The Apply button: every available player that isn't off gets the start volume, and
        any hand-change takeover is cleared."""
        self.manual.clear()
        for pid in self.players:
            st = self.hass.states.get(pid)
            if st is not None and st.state != STATE_OFF:
                await self.async_apply(pid, "manual")

    async def _enforce_cap(self, pid: str, st: State) -> None:
        if not self.enabled or st.state != STATE_PLAYING or self._skipped(st):
            return
        cap = self.cap
        level = st.attributes.get(ATTR_MEDIA_VOLUME_LEVEL)
        if cap is None or not isinstance(level, (int, float)):
            return
        if level * 100 > cap + 0.5:
            await self._set_volume(pid, cap, "quiet" if self.quiet_active else "cap")

    def _taken_over(self, pid: str) -> bool:
        since = self.manual.get(pid)
        if since is None:
            return False
        reset = float(self.opt(CONF_AUTORESET) or 0)
        if reset > 0 and dt_util.utcnow() - since >= timedelta(minutes=reset):
            self.manual.pop(pid, None)
            return False
        return True

    def _adapt(self) -> None:
        """The minute tick while adapting: start ramping every playing player that is off the
        start volume and hasn't been taken over."""
        goal = self.start_volume
        if goal is None or self.quiet_active:
            return
        for pid in self.players:
            if pid in self._ramping:
                continue
            st = self.hass.states.get(pid)
            if st is None or st.state != STATE_PLAYING or self._skipped(st) or self._taken_over(pid):
                continue
            level = st.attributes.get(ATTR_MEDIA_VOLUME_LEVEL)
            if isinstance(level, (int, float)) and abs(goal - level * 100) >= 1:
                self._ramping[pid] = "adapt"
        self._start_ramp()

    def _start_ramp(self) -> None:
        if self._ramping and (self._ramp_task is None or self._ramp_task.done()):
            self._ramp_task = self.entry.async_create_background_task(
                self.hass, self._ramp(), f"adaptive_audio ramp {self.entry.entry_id}"
            )

    async def _ramp(self) -> None:
        """Move ramping players 1 % at a time toward the start volume, `max_rate` steps a
        minute, until each one gets there (or stops playing, is taken over, or quiet starts)."""
        while self._ramping:
            goal = self.start_volume
            if not self.enabled or self.quiet_active or goal is None:
                self._ramping.clear()
                return
            for pid, reason in list(self._ramping.items()):
                st = self.hass.states.get(pid)
                level = None if st is None else st.attributes.get(ATTR_MEDIA_VOLUME_LEVEL)
                if (
                    st is None
                    or st.state != STATE_PLAYING
                    or self._skipped(st)
                    or self._taken_over(pid)
                    or not isinstance(level, (int, float))
                    or (reason == "adapt" and not self.adapt)
                ):
                    self._ramping.pop(pid, None)
                    continue
                expected = self._expected.get(pid)
                if expected is not None and abs(level - expected) <= _TOLERANCE:
                    level = expected  # step from what we set, not a rounded or late report
                diff = goal - level * 100
                if abs(diff) < 0.5:
                    self._ramping.pop(pid, None)
                    continue
                if abs(diff) <= 1:
                    self._ramping.pop(pid, None)
                await self._set_volume(pid, level * 100 + max(-1.0, min(1.0, diff)), reason)
            if self._ramping:
                await asyncio.sleep(60 / max(1.0, float(self.opt(CONF_MAX_RATE))))

    async def _leave_quiet(self) -> None:
        """Quiet just turned off: bring playing players back to the start volume."""
        if not self.enabled:
            return
        self.manual.clear()
        if self.opt(CONF_QUIET_INSTANT):
            for pid in self.players:
                st = self.hass.states.get(pid)
                if st is not None and st.state == STATE_PLAYING:
                    await self.async_apply(pid, "quiet off")
            return
        for pid in self.players:
            self._ramping[pid] = "quiet off"
        self._start_ramp()

    # ---- events --------------------------------------------------------------------------

    @callback
    def _on_player(self, event: Event[EventStateChangedData]) -> None:
        pid = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None:
            return
        now = dt_util.utcnow()
        was_playing = old is not None and old.state == STATE_PLAYING
        if was_playing and new.state != STATE_PLAYING:
            self._stopped_at[pid] = now
            return
        if new.state != STATE_PLAYING:
            return
        if not was_playing:
            if old is None:  # the entity just appeared (startup); not a fresh start
                return
            stopped = self._stopped_at.get(pid)
            gap = timedelta(minutes=float(self.opt(CONF_IDLE_GAP)))
            if stopped is None or now - stopped >= gap:
                self.manual.pop(pid, None)
                self.hass.async_create_task(self.async_apply(pid, "start"))
            return
        # Playing -> playing: a volume change is either ours or a hand change.
        level = new.attributes.get(ATTR_MEDIA_VOLUME_LEVEL)
        if old.attributes.get(ATTR_MEDIA_VOLUME_LEVEL) == level or not isinstance(level, (int, float)):
            return
        expected = self._expected.get(pid)
        if expected is None or abs(level - expected) > _TOLERANCE:
            if pid not in self.manual:
                self.manual[pid] = now
                self.notify()
        self.hass.async_create_task(self._enforce_cap(pid, new))

    @callback
    def _on_cap_entity(self, event: Event[EventStateChangedData]) -> None:
        self.cap_changed()

    @callback
    def cap_changed(self) -> None:
        """The cap may have turned on: pull playing players down to it."""
        for pid in self.players:
            if (st := self.hass.states.get(pid)) is not None:
                self.hass.async_create_task(self._enforce_cap(pid, st))
        self.notify()

    @callback
    def _on_time_entity(self, event: Event[EventStateChangedData]) -> None:
        self._build()
        self.cap_changed()

    @callback
    def _on_quiet_entity(self, event: Event[EventStateChangedData]) -> None:
        self.quiet_changed()

    @callback
    def quiet_changed(self) -> None:
        """Quiet may have turned on or off: pull playing players down if it turned on, bring
        them back up if it turned off."""
        now_quiet = self.quiet_active
        if now_quiet and not self._was_quiet:
            self._ramping.clear()
            for pid in self.players:
                if (st := self.hass.states.get(pid)) is not None:
                    self.hass.async_create_task(self._enforce_cap(pid, st))
        elif self._was_quiet and not now_quiet:
            self.hass.async_create_task(self._leave_quiet())
        self._was_quiet = now_quiet
        self.notify()

    @callback
    def quiet_volume_changed(self) -> None:
        """A lower quiet volume applies at once to anything playing above it."""
        if self.quiet_active:
            for pid in self.players:
                if (st := self.hass.states.get(pid)) is not None:
                    self.hass.async_create_task(self._enforce_cap(pid, st))
        self.notify()

    @callback
    def _on_tick(self, _now: datetime) -> None:
        if self.enabled and self.adapt:
            self._adapt()
        self.notify()
