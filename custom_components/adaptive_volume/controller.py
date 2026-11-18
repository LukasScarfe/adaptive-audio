"""The per-instance controller: watches the players and sets their volume.

Rules:
- A player that starts playing after `idle_gap` minutes of not playing gets the start volume:
  the quiet volume while quiet is active, else the schedule's target, never above the cap.
- Mid-play the volume is left alone, except that a change above the cap is pulled back to
  the cap (during cap hours, or at any time while quiet is active, when the cap is the
  quiet volume). Turning quiet on pulls playing players down to the quiet volume.
- A player whose source is in `skip_sources` (e.g. the turntable's Line In) is never touched.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_VOLUME_LEVEL,
    DOMAIN as MP_DOMAIN,
    SERVICE_VOLUME_SET,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    STATE_OFF,
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from . import schedule
from .const import (
    CONF_CAP_ENABLED,
    CONF_CAP_END,
    CONF_CAP_START,
    CONF_CAP_VOLUME,
    CONF_IDLE_GAP,
    CONF_MODE,
    CONF_PLAYERS,
    CONF_POINTS,
    CONF_QUIET_ENTITY,
    CONF_QUIET_STATE,
    CONF_QUIET_VOLUME,
    CONF_SKIP_SOURCES,
    DEFAULTS,
)

_LOGGER = logging.getLogger(__name__)


class AdaptiveVolumeController:
    """State and behaviour for one Adaptive Volume instance (config entry)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.enabled = True  # set by the Enabled switch when it restores
        self.quiet_switch = False  # set by the Quiet switch when it restores
        self.last_applied: dict[str, dict] = {}
        self._stopped_at: dict[str, datetime | None] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._was_quiet = False
        try:
            self.points = schedule.parse_points(self.opt(CONF_POINTS))
            self.schedule_error: str | None = None
        except schedule.ScheduleError as err:
            self.points = []
            self.schedule_error = str(err)
            _LOGGER.error("%s: bad schedule: %s", entry.title, err)

    # ---- options -------------------------------------------------------------------------

    def opt(self, key: str):
        return self.entry.options.get(key, DEFAULTS.get(key))

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
            # Not playing now: count the gap from when its state last changed.
            self._stopped_at[pid] = None if st is None or st.state == STATE_PLAYING else st.last_changed
        self._unsubs.append(
            async_track_state_change_event(self.hass, self.players, self._on_player)
        )
        if quiet_entity := self.opt(CONF_QUIET_ENTITY):
            self._unsubs.append(
                async_track_state_change_event(self.hass, [quiet_entity], self._on_quiet_entity)
            )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._on_tick, timedelta(minutes=1))
        )
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

    # ---- what the volume should be -------------------------------------------------------

    def _now_minutes(self) -> int:
        now = dt_util.now()
        return now.hour * 60 + now.minute

    def _sun_minutes(self, event: str) -> int | None:
        when = get_astral_event_date(self.hass, event, dt_util.now().date())
        if when is None:
            return None
        local = dt_util.as_local(when)
        return local.hour * 60 + local.minute

    @property
    def target(self) -> float | None:
        """The schedule's volume now (percent), or None if the schedule is broken."""
        if not self.points:
            return None
        sunrise = sunset = None
        if schedule.uses_sun(self.points):
            sunrise = self._sun_minutes(SUN_EVENT_SUNRISE)
            sunset = self._sun_minutes(SUN_EVENT_SUNSET)
        try:
            return schedule.target_volume(
                self._now_minutes(), self.points, self.opt(CONF_MODE), sunrise, sunset
            )
        except schedule.ScheduleError as err:
            _LOGGER.warning("%s: %s", self.entry.title, err)
            return None

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
        """The volume (percent) a fresh start gets now."""
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
        """The Apply button: every available player that isn't off gets the start volume."""
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
                self.hass.async_create_task(self.async_apply(pid, "start"))
            return
        # Playing -> playing: only a volume change matters, and only for the cap.
        if old.attributes.get(ATTR_MEDIA_VOLUME_LEVEL) != new.attributes.get(ATTR_MEDIA_VOLUME_LEVEL):
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
        self.notify()
