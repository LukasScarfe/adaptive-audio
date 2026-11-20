"""Config and options flow: one page, the same for setup and Configure.

Collapsible sections: Speakers and behaviour, Schedule, Wake / Evening / Bedtime, Quiet and
night cap. Options are stored flat except the three anchors, so the flat sections are unpacked
on submit. A submit saves straight away unless something is missing or the schedule is broken.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from . import curve, schedule
from .const import (
    A_ENTITY,
    A_RAMP,
    A_TIME,
    ANCHORS,
    CONF_AUTORESET,
    CONF_CAP_ENABLED,
    CONF_CAP_END,
    CONF_CAP_END_ENTITY,
    CONF_CAP_ENTITY,
    CONF_CAP_START,
    CONF_CAP_START_ENTITY,
    CONF_CAP_VOLUME,
    CONF_CURVE,
    CONF_DAY_VOLUME,
    CONF_EVENING_VOLUME,
    CONF_IDLE_GAP,
    CONF_MAX_RATE,
    CONF_NAME,
    CONF_NIGHT_VOLUME,
    CONF_PLAYERS,
    CONF_POINTS,
    CONF_QUIET_ENTITY,
    CONF_QUIET_INSTANT,
    CONF_QUIET_STATE,
    CONF_QUIET_VOLUME,
    CONF_SCHEDULE_TYPE,
    CONF_SKIP_SOURCES,
    CONF_USE_EVENING,
    CURVES,
    DEFAULTS,
    DOMAIN,
    SCHEDULE_TYPES,
    TESTER_URL,
)
from .controller import entity_minute, sun_minutes


def _num(lo, hi, unit=None, step=1, mode="box"):
    cfg = {"min": lo, "max": hi, "step": step, "mode": mode}
    if unit:
        cfg["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**cfg))


def _select(options, key):
    return selector.SelectSelector(selector.SelectSelectorConfig(options=options, translation_key=key))


_PERCENT = _num(0, 100, "%", mode="slider")
_PLAYERS = selector.EntitySelector(selector.EntitySelectorConfig(domain="media_player", multiple=True))
# A time of day: a time helper, a time entity, or a timestamp sensor (e.g. Sun next rising).
_TIME_ENTITY = selector.EntitySelector(
    selector.EntitySelectorConfig(
        filter=[
            selector.EntityFilterSelectorConfig(domain="input_datetime"),
            selector.EntityFilterSelectorConfig(domain="time"),
            selector.EntityFilterSelectorConfig(domain="sensor", device_class="timestamp"),
        ]
    )
)


_ANCHOR = vol.Schema(
    {
        vol.Optional(A_ENTITY): _TIME_ENTITY,
        vol.Required(A_TIME): selector.TimeSelector(),
        vol.Required(A_RAMP): _num(0, 480, "min"),
    }
)

# Flat sections: their fields are stored as top-level options.
SPEAKERS = vol.Schema(
    {
        vol.Required(CONF_PLAYERS): _PLAYERS,
        vol.Optional(CONF_SKIP_SOURCES): selector.TextSelector(),
        vol.Required(CONF_IDLE_GAP): _num(0, 720, "min"),
        vol.Required(CONF_AUTORESET): _num(0, 1440, "min"),
        vol.Required(CONF_MAX_RATE): _num(1, 100, "%/min"),
    }
)

SCHEDULE = vol.Schema(
    {
        vol.Required(CONF_SCHEDULE_TYPE): _select(SCHEDULE_TYPES, "schedule_type"),
        vol.Required(CONF_CURVE): _select(CURVES, "curve"),
        vol.Required(CONF_DAY_VOLUME): _PERCENT,
        vol.Required(CONF_USE_EVENING): selector.BooleanSelector(),
        vol.Required(CONF_EVENING_VOLUME): _PERCENT,
        vol.Required(CONF_NIGHT_VOLUME): _PERCENT,
        vol.Required(CONF_POINTS): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
    }
)

QUIET_CAP = vol.Schema(
    {
        vol.Required(CONF_QUIET_VOLUME): _PERCENT,
        vol.Optional(CONF_QUIET_ENTITY): selector.EntitySelector(),
        vol.Optional(CONF_QUIET_STATE): selector.TextSelector(),
        vol.Required(CONF_QUIET_INSTANT): selector.BooleanSelector(),
        vol.Required(CONF_CAP_ENABLED): selector.BooleanSelector(),
        vol.Optional(CONF_CAP_ENTITY): selector.EntitySelector(),
        vol.Required(CONF_CAP_VOLUME): _PERCENT,
        vol.Required(CONF_CAP_START): selector.TimeSelector(),
        vol.Optional(CONF_CAP_START_ENTITY): _TIME_ENTITY,
        vol.Required(CONF_CAP_END): selector.TimeSelector(),
        vol.Optional(CONF_CAP_END_ENTITY): _TIME_ENTITY,
    }
)

FLAT = {"speakers": SPEAKERS, "schedule": SCHEDULE, "quiet_cap": QUIET_CAP}


def page_schema(with_name: bool) -> vol.Schema:
    fields: dict = {}
    if with_name:
        fields[vol.Required(CONF_NAME)] = selector.TextSelector()
    fields[vol.Required("speakers")] = section(SPEAKERS, {"collapsed": not with_name})
    fields[vol.Required("schedule")] = section(SCHEDULE, {"collapsed": False})
    for a in ANCHORS:
        fields[vol.Required(a)] = section(_ANCHOR, {"collapsed": a == "evening"})
    fields[vol.Required("quiet_cap")] = section(QUIET_CAP, {"collapsed": True})
    return vol.Schema(fields)


def _suggested(options: dict[str, Any]) -> dict[str, Any]:
    """The page's suggested values: flat options regrouped into their sections."""
    full = _with_defaults(options)
    out = {CONF_NAME: options.get(CONF_NAME, "")}
    for sec, schema in FLAT.items():
        out[sec] = {str(k): full[str(k)] for k in schema.schema if str(k) in full}
    for a in ANCHORS:
        out[a] = full[a]
    return out


def _apply(opts: dict[str, Any], user_input: dict[str, Any], with_name: bool) -> dict[str, Any]:
    out = dict(opts)
    if with_name:
        out[CONF_NAME] = str(user_input.get(CONF_NAME, "")).strip()
    for sec, schema in FLAT.items():
        out = _merge(out, schema, user_input.get(sec) or {})
    for a in ANCHORS:  # each anchor is exactly entity (optional), time and ramp
        new = {k: v for k, v in (user_input.get(a) or {}).items() if not _empty(v)}
        for k in (A_TIME, A_RAMP):
            new.setdefault(k, (opts.get(a) or {}).get(k, DEFAULTS[a][k]))
        out[a] = new
    return out


def _empty(v) -> bool:
    return v is None or v == "" or v == []


def _merge(opts: dict[str, Any], schema: vol.Schema, user_input: dict[str, Any]) -> dict[str, Any]:
    """Apply a form's input. An optional field left empty is removed, so clearing one really
    clears it (HA leaves cleared fields out of user_input)."""
    out = dict(opts)
    for key in schema.schema:
        name = str(key)
        if _empty(user_input.get(name)):
            if isinstance(key, vol.Optional):
                out.pop(name, None)
        else:
            out[name] = user_input[name]
    return out


def _with_defaults(options: dict[str, Any]) -> dict[str, Any]:
    """Options with defaults filled in, sections merged, for showing a form."""
    out = {**DEFAULTS, **options}
    for a in ANCHORS:
        out[a] = {**DEFAULTS[a], **options.get(a, {})}
    return out


def tester_url(hass, options: dict[str, Any]) -> str:
    """The online tester, opened with these settings (time entities and sun times as they are
    today). The settings ride in the URL hash, so they never reach a server."""
    try:
        o = _with_defaults(options)
        em = lambda e: entity_minute(hass, e)  # noqa: E731
        clock = lambda m: f"{int(m) // 60 % 24:02d}:{int(m) % 60:02d}"  # noqa: E731
        rise, set_ = sun_minutes(hass, dt_util.now().date())
        keys = (CONF_SCHEDULE_TYPE, CONF_CURVE, CONF_DAY_VOLUME, CONF_USE_EVENING, CONF_EVENING_VOLUME,
                CONF_NIGHT_VOLUME, CONF_POINTS, CONF_QUIET_VOLUME, CONF_CAP_VOLUME)
        out: dict[str, Any] = {k: o[k] for k in keys}
        out[CONF_CAP_ENABLED] = bool(o[CONF_CAP_ENABLED] or o.get(CONF_CAP_ENTITY))
        start, end = curve.cap_window(o, em)
        out[CONF_CAP_START], out[CONF_CAP_END] = clock(start), clock(end)
        for name, t in curve.anchors({**o, CONF_USE_EVENING: True}, em):
            out[name] = {A_TIME: clock(t.at), A_RAMP: t.ramp}
        if rise is not None and set_ is not None:
            out["rise"], out["set"] = clock(rise), clock(set_)
        raw = json.dumps(out, separators=(",", ":")).encode()
        return f"{TESTER_URL}#{base64.urlsafe_b64encode(raw).decode().rstrip('=')}"
    except Exception:  # noqa: BLE001 - never let the link break the page
        return TESTER_URL


def check_schedule(hass, options: dict[str, Any]) -> str | None:
    """None if the schedule works today, else the error text."""
    try:
        rise = set_ = None
        if curve.uses_sun(options):
            rise, set_ = sun_minutes(hass, dt_util.now().date())
        curve.builder(options, rise, set_, lambda e: entity_minute(hass, e))
    except schedule.ScheduleError as err:
        return str(err)
    return None


class _Page:
    """The one page, shared by setup and Configure. `self.opts` holds the pending options."""

    opts: dict[str, Any]
    _with_name = False

    _taken = ""

    def _page(self, step_id: str, errors: dict[str, str] | None = None):
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(page_schema(self._with_name), _suggested(self.opts)),
            errors=errors or {},
            description_placeholders={**self._placeholders(), "taken": self._taken},
        )

    def _own_entry_id(self) -> str | None:
        return None

    def _speakers_taken(self) -> str:
        """'Kitchen is already in Living room', for speakers another instance controls, or ''."""
        own = self._own_entry_id()
        taken = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == own:
                continue
            for pid in set(self.opts.get(CONF_PLAYERS) or []) & set(entry.options.get(CONF_PLAYERS) or []):
                st = self.hass.states.get(pid)
                name = st.attributes.get("friendly_name", pid) if st else pid
                taken.append(f"{name} is already in {entry.title}")
        return ", ".join(sorted(taken))

    def _placeholders(self) -> dict[str, str]:
        err = check_schedule(self.hass, self.opts)
        rise, set_ = sun_minutes(self.hass, dt_util.now().date())
        sun = ""
        if rise is not None and set_ is not None:
            sun = f"Today: sunrise {rise // 60:02d}:{rise % 60:02d}, sunset {set_ // 60:02d}:{set_ % 60:02d}."
        return {"sun": sun, "error": err or "", "tester": tester_url(self.hass, self.opts)}

    async def _submit(self, step_id: str, user_input: dict[str, Any]):
        """Apply the input; show the page again if something's wrong, else None."""
        self.opts = _apply(self.opts, user_input, self._with_name)
        if self._with_name and (not self.opts.get(CONF_NAME) or not self.opts.get(CONF_PLAYERS)):
            return self._page(step_id, {"base": "need_speakers"})
        self._taken = self._speakers_taken()
        if self._taken:
            return self._page(step_id, {"base": "speaker_taken"})
        if check_schedule(self.hass, self.opts) is not None:
            return self._page(step_id, {"base": "bad_schedule"})
        return None


class AdaptiveAudioConfigFlow(_Page, ConfigFlow, domain=DOMAIN):
    VERSION = 1
    _with_name = True

    def __init__(self) -> None:
        self.opts = dict(DEFAULTS)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self._page("user")
        if (again := await self._submit("user", user_input)) is not None:
            return again
        opts = dict(self.opts)
        name = opts.pop(CONF_NAME)
        return self.async_create_entry(title=name, data={}, options=opts)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AdaptiveAudioOptionsFlow()


class AdaptiveAudioOptionsFlow(_Page, OptionsFlow):
    def __init__(self) -> None:
        self.opts: dict[str, Any] | None = None

    def _own_entry_id(self) -> str | None:
        return self.config_entry.entry_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.opts is None:
            self.opts = dict(self.config_entry.options)
        if user_input is None:
            return self._page("init")
        if (again := await self._submit("init", user_input)) is not None:
            return again
        return self.async_create_entry(data=self.opts)
