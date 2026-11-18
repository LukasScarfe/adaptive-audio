"""The per-instance controller: watches the players and sets their volume.

Rules:
- A player that starts playing after `idle_gap` minutes of not playing gets the start volume:
  the quiet volume while quiet is active, else the schedule's target, never above the cap.
- With "Adapt while playing" on, every minute a playing player moves toward that volume by at
  most `adapt_step` %. A hand change (any volume change Adaptive Volume didn't make) stops
  adapting that player until its next fresh start, or for `autoreset` minutes if that is set.
- With it off, the volume is left alone mid-play.
- Either way, a raise above the cap is pulled back to the cap (during cap hours, or at any time
  while quiet is active, when the cap is the quiet volume). Turning quiet on pulls playing
  players down to the quiet volume.
- A player whose source is in `skip_sources` (e.g. the turntable's Line In) is never touched.
"""

from __future__ import annotations

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
    CONF_ADAPT_STEP,
    CONF_AUTORESET,
    CONF_CAP_ENABLED,
    CONF_CAP_END,
    CONF_CAP_START,
    CONF_CAP_VOLUME,
    CONF_IDLE_GAP,
    CONF_PLAYERS,
    CONF_QUIET_ENTITY,
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


class AdaptiveVolumeController:
    """State and behaviour for one Adaptive Volume instance (config entry)."""

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
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, timedelta(minutes=1)))
        self._was_quiet = self.quiet_active

    @callback
    def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

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
            self._fn, self.marks = curve.builder(self.entry.options, rise, set_)
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
    def cap_hours_active(self) -> bool:
        if not self.opt(CONF_CAP_ENABLED):
            return False
        return schedule.in_window(
            self._now_minutes(),
            schedule.parse_clock(self.opt(CONF_CAP_START)),
            schedule.parse_clock(self.opt(CONF_CAP_END)),
        )

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

    async def _adapt(self) -> None:
        """One adapting step for every playing player that hasn't been taken over."""
        goal = self.start_volume
        if goal is None:
            return
        step = max(0.5, float(self.opt(CONF_ADAPT_STEP)))
        for pid in self.players:
            st = self.hass.states.get(pid)
            if st is None or st.state != STATE_PLAYING or self._skipped(st) or self._taken_over(pid):
                continue
            level = st.attributes.get(ATTR_MEDIA_VOLUME_LEVEL)
            if not isinstance(level, (int, float)):
                continue
            diff = goal - level * 100
            if abs(diff) < 1:
                continue
            await self._set_volume(pid, level * 100 + max(-step, min(step, diff)), "adapt")

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
    def _on_quiet_entity(self, event: Event[EventStateChangedData]) -> None:
        self.quiet_changed()

    @callback
    def quiet_changed(self) -> None:
        """Quiet may have turned on or off: pull playing players down if it turned on."""
        now_quiet = self.quiet_active
        if now_quiet and not self._was_quiet:
            for pid in self.players:
                if (st := self.hass.states.get(pid)) is not None:
                    self.hass.async_create_task(self._enforce_cap(pid, st))
        self._was_quiet = now_quiet
        self.notify()

    @callback
    def _on_tick(self, _now: datetime) -> None:
        if self.enabled and self.adapt:
            self.hass.async_create_task(self._adapt())
        self.notify()
