"""Config and options flow. Setup asks for a name and the speakers, then the settings;
Configure shows every setting again."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import schedule
from .const import (
    CONF_CAP_ENABLED,
    CONF_CAP_END,
    CONF_CAP_START,
    CONF_CAP_VOLUME,
    CONF_IDLE_GAP,
    CONF_MODE,
    CONF_NAME,
    CONF_PLAYERS,
    CONF_POINTS,
    CONF_QUIET_ENTITY,
    CONF_QUIET_STATE,
    CONF_QUIET_VOLUME,
    CONF_SKIP_SOURCES,
    DEFAULTS,
    DOMAIN,
    MODES,
)

_PERCENT = selector.NumberSelector(
    selector.NumberSelectorConfig(min=0, max=100, step=1, unit_of_measurement="%", mode="slider")
)
_PLAYERS = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="media_player", multiple=True)
)


def _settings_schema(with_players: bool) -> vol.Schema:
    fields: dict = {}
    if with_players:
        fields[vol.Required(CONF_PLAYERS)] = _PLAYERS
    fields.update(
        {
            vol.Required(CONF_MODE): selector.SelectSelector(
                selector.SelectSelectorConfig(options=MODES, translation_key="mode")
            ),
            vol.Required(CONF_POINTS): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
            vol.Required(CONF_IDLE_GAP): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=720, step=1, unit_of_measurement="min", mode="box"
                )
            ),
            vol.Optional(CONF_SKIP_SOURCES): selector.TextSelector(),
            vol.Required(CONF_QUIET_VOLUME): _PERCENT,
            vol.Optional(CONF_QUIET_ENTITY): selector.EntitySelector(),
            vol.Optional(CONF_QUIET_STATE): selector.TextSelector(),
            vol.Required(CONF_CAP_ENABLED): selector.BooleanSelector(),
            vol.Required(CONF_CAP_START): selector.TimeSelector(),
            vol.Required(CONF_CAP_END): selector.TimeSelector(),
            vol.Required(CONF_CAP_VOLUME): _PERCENT,
        }
    )
    return vol.Schema(fields)


def _validate(user_input: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    try:
        schedule.parse_points(user_input.get(CONF_POINTS, ""))
    except schedule.ScheduleError as err:
        return {CONF_POINTS: "bad_schedule"}, {"error": str(err)}
    return {}, {}


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    """Drop empty optional fields, so clearing one in Configure really clears it."""
    return {k: v for k, v in user_input.items() if v not in (None, "")}


class AdaptiveVolumeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._name = ""
        self._players: list[str] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._name = user_input[CONF_NAME].strip()
            self._players = user_input[CONF_PLAYERS]
            return await self.async_step_settings()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_NAME): selector.TextSelector(), vol.Required(CONF_PLAYERS): _PLAYERS}
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            errors, found = _validate(user_input)
            placeholders.update(found)
            if not errors:
                options = {CONF_PLAYERS: self._players, **_clean(user_input)}
                return self.async_create_entry(title=self._name, data={}, options=options)
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                _settings_schema(with_players=False), user_input or DEFAULTS
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AdaptiveVolumeOptionsFlow()


class AdaptiveVolumeOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        if user_input is not None:
            errors, found = _validate(user_input)
            placeholders.update(found)
            if not errors:
                return self.async_create_entry(data=_clean(user_input))
        current = {**DEFAULTS, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _settings_schema(with_players=True), user_input or current
            ),
            errors=errors,
            description_placeholders=placeholders,
        )
