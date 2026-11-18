"""Config and options flow.

Setup: name + speakers -> schedule (type and curve) -> Simple anchors or Custom points ->
preview of the curve -> create. Configure is a menu: Speakers & behaviour, Schedule, Quiet &
night cap, Preview, Save. Nothing is saved until Save (or the last setup step).
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
    A_EARLIEST,
    A_KIND,
    A_LATEST,
    A_OFFSET,
    A_RAMP,
    A_TIME,
    ALIGNS,
    ANCHOR_KINDS,
    ANCHORS,
    CONF_ADAPT_STEP,
    CONF_ALIGN,
    CONF_AUTORESET,
    CONF_CAP_ENABLED,
    CONF_CAP_END,
    CONF_CAP_START,
    CONF_CAP_VOLUME,
    CONF_CURVE,
    CONF_DAY_VOLUME,
    CONF_EVENING_VOLUME,
    CONF_IDLE_GAP,
    CONF_MODE,
    CONF_NAME,
    CONF_NIGHT_VOLUME,
    CONF_PLAYERS,
    CONF_POINTS,
    CONF_QUIET_ENTITY,
    CONF_QUIET_STATE,
    CONF_QUIET_VOLUME,
    CONF_SCHEDULE_TYPE,
    CONF_SKIP_SOURCES,
    CONF_STEEPNESS,
    CONF_USE_EVENING,
    CURVES,
    DEFAULTS,
    DOMAIN,
    SCHEDULE_TYPES,
)
from .controller import sun_minutes

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


def speakers_schema(with_players: bool = True) -> vol.Schema:
    fields: dict = {}
    if with_players:
        fields[vol.Required(CONF_PLAYERS)] = _PLAYERS
    fields.update(
        {
            vol.Required(CONF_IDLE_GAP): _num(0, 720, "min"),
            vol.Optional(CONF_SKIP_SOURCES): selector.TextSelector(),
            vol.Required(CONF_ADAPT_STEP): _num(0.5, 10, "%", step=0.5),
            vol.Required(CONF_AUTORESET): _num(0, 1440, "min"),
        }
    )
    return vol.Schema(fields)


SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCHEDULE_TYPE): _select(SCHEDULE_TYPES, "schedule_type"),
        vol.Required(CONF_CURVE): _select(CURVES, "curve"),
        vol.Required(CONF_STEEPNESS): _num(1, 20, step=0.5, mode="slider"),
        vol.Required(CONF_ALIGN): _select(ALIGNS, "align"),
    }
)

_ANCHOR = vol.Schema(
    {
        vol.Required(A_KIND): _select(ANCHOR_KINDS, "anchor_kind"),
        vol.Required(A_TIME): selector.TimeSelector(),
        vol.Required(A_OFFSET): _num(-360, 360, "min"),
        vol.Optional(A_EARLIEST): selector.TimeSelector(),
        vol.Optional(A_LATEST): selector.TimeSelector(),
        vol.Required(A_RAMP): _num(0, 480, "min"),
    }
)

SIMPLE_SCHEMA = vol.Schema(
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

CUSTOM_SCHEMA = vol.Schema(
    {vol.Required(CONF_POINTS): selector.TextSelector(selector.TextSelectorConfig(multiline=True))}
)

QUIET_CAP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_QUIET_VOLUME): _PERCENT,
        vol.Optional(CONF_QUIET_ENTITY): selector.EntitySelector(),
        vol.Optional(CONF_QUIET_STATE): selector.TextSelector(),
        vol.Required(CONF_CAP_ENABLED): selector.BooleanSelector(),
        vol.Required(CONF_CAP_START): selector.TimeSelector(),
        vol.Required(CONF_CAP_END): selector.TimeSelector(),
        vol.Required(CONF_CAP_VOLUME): _PERCENT,
    }
)


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """Drop empty optional fields (also inside sections), so clearing one really clears it."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            v = _clean(v)
        if v not in (None, ""):
            out[k] = v
    return out


def _with_defaults(options: dict[str, Any]) -> dict[str, Any]:
    """Options with defaults filled in, sections merged, for showing a form."""
    out = {**DEFAULTS, **options}
    for a in ANCHORS:
        out[a] = {**DEFAULTS[a], **options.get(a, {})}
    out[CONF_SCHEDULE_TYPE] = curve.schedule_type(options) if options else DEFAULTS[CONF_SCHEDULE_TYPE]
    out[CONF_CURVE] = curve.curve_name(options) if options else DEFAULTS[CONF_CURVE]
    return out


def check_schedule(hass, options: dict[str, Any]) -> str | None:
    """None if the schedule works today, else the error text."""
    try:
        rise = set_ = None
        if curve.uses_sun(options):
            rise, set_ = sun_minutes(hass, dt_util.now().date())
        curve.builder(options, rise, set_)
    except schedule.ScheduleError as err:
        return str(err)
    return None


class _Steps:
    """Form steps shared by setup and Configure. `self.opts` holds the pending options;
    `_after_schedule()` and `_after_step()` say where each flow goes next."""

    opts: dict[str, Any]

    def _form(self, step_id, schema, errors=None, placeholders=None):
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, _with_defaults(self.opts)),
            errors=errors or {},
            description_placeholders={"error": "", **(placeholders or {})},
        )

    async def async_step_schedule(self, user_input=None):
        if user_input is not None:
            self.opts.update(user_input)
            self.opts.pop(CONF_MODE, None)  # superseded 0.1 option
            if user_input[CONF_SCHEDULE_TYPE] == "custom":
                return await self.async_step_custom()
            return await self.async_step_simple()
        return self._form("schedule", SCHEDULE_SCHEMA)

    async def _schedule_form(self, step_id, schema, user_input):
        if user_input is not None:
            pending = {**self.opts, **_clean(user_input)}
            if step_id == "simple":
                for a in ANCHORS:  # clearing earliest/latest must remove them
                    pending[a] = _clean(user_input.get(a, {}))
            if (err := check_schedule(self.hass, pending)) is None:
                self.opts = pending
                return await self.async_step_preview()
            return self._form(step_id, schema, {"base": "bad_schedule"}, {"error": err})
        return self._form(step_id, schema)

    async def async_step_simple(self, user_input=None):
        return await self._schedule_form("simple", SIMPLE_SCHEMA, user_input)

    async def async_step_custom(self, user_input=None):
        return await self._schedule_form("custom", CUSTOM_SCHEMA, user_input)

    async def async_step_preview(self, user_input=None):
        if user_input is not None:
            preview.forget(self.hass, self.flow_id)
            return await self._after_preview()
        try:
            url = preview.preview_url(self.hass, self.flow_id, self.opts)
            image = f"![Volume through the day]({url})"
        except Exception:  # noqa: BLE001 - no request context to sign with; skip the picture
            _LOGGER.debug("preview image unavailable", exc_info=True)
            image = "(Preview image unavailable here; the card shows the same curve.)"
        rise, set_ = sun_minutes(self.hass, dt_util.now().date())
        sun = f"Today: sunrise {rise // 60:02d}:{rise % 60:02d}, sunset {set_ // 60:02d}:{set_ % 60:02d}." if rise is not None and set_ is not None else ""
        return self.async_show_form(
            step_id="preview",
            data_schema=vol.Schema({}),
            description_placeholders={"image": image, "sun": sun},
        )


class AdaptiveVolumeConfigFlow(_Steps, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._name = ""
        self.opts = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._name = user_input[CONF_NAME].strip()
            self.opts = {k: v for k, v in DEFAULTS.items()}
            self.opts[CONF_PLAYERS] = user_input[CONF_PLAYERS]
            return await self.async_step_schedule()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_NAME): selector.TextSelector(), vol.Required(CONF_PLAYERS): _PLAYERS}
            ),
        )

    async def _after_preview(self):
        return self.async_create_entry(title=self._name, data={}, options=self.opts)

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
        return self.async_show_menu(
            step_id="init", menu_options=["speakers", "schedule", "quiet_cap", "preview", "save"]
        )

    async def async_step_speakers(self, user_input=None):
        if user_input is not None:
            self.opts = {**self.opts, **user_input}
            if not user_input.get(CONF_SKIP_SOURCES):
                self.opts.pop(CONF_SKIP_SOURCES, None)
            return await self.async_step_init()
        return self._form("speakers", speakers_schema())

    async def async_step_quiet_cap(self, user_input=None):
        if user_input is not None:
            self.opts = {**self.opts, **user_input}
            for k in (CONF_QUIET_ENTITY, CONF_QUIET_STATE):
                if not user_input.get(k):
                    self.opts.pop(k, None)
            return await self.async_step_init()
        return self._form("quiet_cap", QUIET_CAP_SCHEMA)

    async def _after_preview(self):
        return await self.async_step_init()

    async def async_step_save(self, user_input=None):
        preview.forget(self.hass, self.flow_id)
        return self.async_create_entry(data=self.opts)
