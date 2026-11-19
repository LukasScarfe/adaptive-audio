"""Config and options flow.

Setup and Configure share one menu: Speakers and behaviour, Schedule, Quiet and night cap, and
Create / Save. Schedule is its own menu with today's curve at the top: Schedule type and curve,
then Times and levels (Simple) or Points (Custom). Every form's button is "Back": it keeps the
changes and returns to the menu above. Nothing is saved until Create / Save.

HA draws a close (X) on every flow dialog and has no back button of its own; the X discards
the pending changes.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from . import curve, http as preview, schedule
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
    CONF_NAME,
    CONF_NIGHT_VOLUME,
    CONF_PLAYERS,
    CONF_POINTS,
    CONF_QUIET_ENTITY,
    CONF_QUIET_STATE,
    CONF_QUIET_VOLUME,
    CONF_SCHEDULE_TYPE,
    CONF_SKIP_SOURCES,
    CONF_USE_EVENING,
    CURVES,
    DEFAULTS,
    DOMAIN,
    RETIRED_OPTIONS,
    SCHEDULE_TYPES,
)
from .controller import entity_minute, sun_minutes

_LOGGER = logging.getLogger(__name__)


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


def speakers_schema(with_name: bool) -> vol.Schema:
    fields: dict = {}
    if with_name:
        fields[vol.Required(CONF_NAME)] = selector.TextSelector()
    fields.update(
        {
            vol.Required(CONF_PLAYERS): _PLAYERS,
            vol.Optional(CONF_SKIP_SOURCES): selector.TextSelector(),
            vol.Required(CONF_IDLE_GAP): _num(0, 720, "min"),
            vol.Required(CONF_AUTORESET): _num(0, 1440, "min"),
        }
    )
    return vol.Schema(fields)


TYPE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCHEDULE_TYPE): _select(SCHEDULE_TYPES, "schedule_type"),
        vol.Required(CONF_CURVE): _select(CURVES, "curve"),
    }
)

_ANCHOR = vol.Schema(
    {
        vol.Optional(A_ENTITY): _TIME_ENTITY,
        vol.Required(A_TIME): selector.TimeSelector(),
        vol.Required(A_RAMP): _num(0, 480, "min"),
    }
)

LEVELS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DAY_VOLUME): _PERCENT,
        vol.Required(CONF_USE_EVENING): selector.BooleanSelector(),
        vol.Required(CONF_EVENING_VOLUME): _PERCENT,
        vol.Required(CONF_NIGHT_VOLUME): _PERCENT,
        vol.Required("wake"): section(_ANCHOR, {"collapsed": False}),
        vol.Required("evening"): section(_ANCHOR, {"collapsed": True}),
        vol.Required("bedtime"): section(_ANCHOR, {"collapsed": False}),
    }
)

POINTS_SCHEMA = vol.Schema(
    {vol.Required(CONF_POINTS): selector.TextSelector(selector.TextSelectorConfig(multiline=True))}
)

QUIET_CAP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_QUIET_VOLUME): _PERCENT,
        vol.Optional(CONF_QUIET_ENTITY): selector.EntitySelector(),
        vol.Optional(CONF_QUIET_STATE): selector.TextSelector(),
        vol.Required(CONF_CAP_ENABLED): selector.BooleanSelector(),
        vol.Optional(CONF_CAP_ENTITY): selector.EntitySelector(),
        vol.Required(CONF_CAP_VOLUME): _PERCENT,
        vol.Required(CONF_CAP_START): selector.TimeSelector(),
        vol.Optional(CONF_CAP_START_ENTITY): _TIME_ENTITY,
        vol.Required(CONF_CAP_END): selector.TimeSelector(),
        vol.Optional(CONF_CAP_END_ENTITY): _TIME_ENTITY,
    }
)


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
    out[CONF_SCHEDULE_TYPE] = curve.schedule_type(options) if options else DEFAULTS[CONF_SCHEDULE_TYPE]
    out[CONF_CURVE] = curve.curve_name(options) if options else DEFAULTS[CONF_CURVE]
    return out


def _finish(options: dict[str, Any]) -> dict[str, Any]:
    """The options to store: retired settings dropped, the schedule type and curve explicit."""
    out = {**options}
    out[CONF_SCHEDULE_TYPE] = curve.schedule_type(options)
    out[CONF_CURVE] = curve.curve_name(options)
    for k in RETIRED_OPTIONS:
        out.pop(k, None)
    return out


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


class _Steps:
    """The menu and forms shared by setup and Configure. `self.opts` holds the pending
    options; `_with_name` and `async_step_save` differ per flow."""

    opts: dict[str, Any]
    _with_name = False

    def _form(self, step_id, schema, errors=None, placeholders=None):
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, _with_defaults(self.opts)),
            errors=errors or {},
            description_placeholders={"error": "", **(placeholders or {})},
        )

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init", menu_options=["speakers", "schedule", "quiet_cap", "save"]
        )

    async def async_step_speakers(self, user_input=None):
        schema = speakers_schema(self._with_name)
        if user_input is not None:
            if self._with_name:
                user_input[CONF_NAME] = str(user_input.get(CONF_NAME, "")).strip()
            self.opts = _merge(self.opts, schema, user_input)
            return await self.async_step_init()
        return self._form("speakers", schema)

    # ---- Schedule: a menu with the curve on top ----------------------------------------

    async def async_step_schedule(self, user_input=None):
        options = ["type", "points" if curve.schedule_type(self.opts) == "custom" else "levels", "back"]
        return self.async_show_menu(step_id="schedule", menu_options=options, description_placeholders=self._preview())

    def _preview(self) -> dict[str, str]:
        err = check_schedule(self.hass, self.opts)
        try:
            url = preview.preview_url(self.hass, self.flow_id, self.opts)
            image = f"![Volume through the day]({url})"
        except Exception:  # noqa: BLE001 - no request context to sign with; skip the picture
            _LOGGER.debug("preview image unavailable", exc_info=True)
            image = "(Preview image unavailable here; the card shows the same curve.)"
        rise, set_ = sun_minutes(self.hass, dt_util.now().date())
        sun = ""
        if rise is not None and set_ is not None:
            sun = f"Today: sunrise {rise // 60:02d}:{rise % 60:02d}, sunset {set_ // 60:02d}:{set_ % 60:02d}."
        if err:
            sun = f"**This schedule can't be used: {err}.** {sun}"
        return {"image": image, "sun": sun}

    async def async_step_back(self, user_input=None):
        return await self.async_step_init()

    async def async_step_type(self, user_input=None):
        if user_input is not None:
            self.opts = _merge(self.opts, TYPE_SCHEMA, user_input)
            return await self.async_step_schedule()
        return self._form("type", TYPE_SCHEMA)

    async def async_step_levels(self, user_input=None):
        if user_input is not None:
            pending = _merge(self.opts, LEVELS_SCHEMA, user_input)
            for a in ANCHORS:  # each anchor is now exactly entity (optional), time and ramp
                old = self.opts.get(a, {})
                new = {k: v for k, v in (user_input.get(a) or {}).items() if not _empty(v)}
                for k in (A_TIME, A_RAMP):
                    new.setdefault(k, old.get(k, DEFAULTS[a][k]))
                pending[a] = new  # drops 0.2's kind/offset/earliest/latest
            return await self._check_and_return("levels", LEVELS_SCHEMA, pending)
        return self._form("levels", LEVELS_SCHEMA)

    async def async_step_points(self, user_input=None):
        if user_input is not None:
            return await self._check_and_return("points", POINTS_SCHEMA, _merge(self.opts, POINTS_SCHEMA, user_input))
        return self._form("points", POINTS_SCHEMA)

    async def _check_and_return(self, step_id, schema, pending):
        if (err := check_schedule(self.hass, pending)) is None:
            self.opts = pending
            return await self.async_step_schedule()
        self.opts, keep = pending, self.opts  # show what was typed, with the error
        form = self._form(step_id, schema, {"base": "bad_schedule"}, {"error": err})
        self.opts = keep
        return form

    async def async_step_quiet_cap(self, user_input=None):
        if user_input is not None:
            self.opts = _merge(self.opts, QUIET_CAP_SCHEMA, user_input)
            return await self.async_step_init()
        return self._form("quiet_cap", QUIET_CAP_SCHEMA)


class AdaptiveVolumeConfigFlow(_Steps, ConfigFlow, domain=DOMAIN):
    VERSION = 1
    _with_name = True

    def __init__(self) -> None:
        self.opts = {k: v for k, v in DEFAULTS.items()}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_init()

    async def async_step_save(self, user_input=None):
        """Create: needs a name and speakers first."""
        if not self.opts.get(CONF_NAME) or not self.opts.get(CONF_PLAYERS):
            return self._form("speakers", speakers_schema(True), {"base": "need_speakers"})
        if check_schedule(self.hass, self.opts) is not None:
            return await self.async_step_schedule()  # its description shows the error
        preview.forget(self.hass, self.flow_id)
        opts = _finish(self.opts)
        name = opts.pop(CONF_NAME)
        return self.async_create_entry(title=name, data={}, options=opts)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AdaptiveVolumeOptionsFlow()


class AdaptiveVolumeOptionsFlow(_Steps, OptionsFlow):
    def __init__(self) -> None:
        self.opts: dict[str, Any] | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.opts is None:
            self.opts = dict(self.config_entry.options)
        return await super().async_step_init(user_input)

    async def async_step_save(self, user_input=None):
        if check_schedule(self.hass, self.opts) is not None:
            return await self.async_step_schedule()  # its description shows the error
        preview.forget(self.hass, self.flow_id)
        return self.async_create_entry(data=_finish(self.opts))
