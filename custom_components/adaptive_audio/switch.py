"""Enabled, Quiet, Adapt and Night cap switches. The first three restore their state across
restarts; Night cap is the `cap_enabled` option, so it is saved with the entry."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_CAP_ENABLED
from .entity import AdaptiveAudioEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    c = entry.runtime_data
    async_add_entities([EnabledSwitch(c, "enabled"), QuietSwitch(c, "quiet"), AdaptSwitch(c, "adapt"), CapSwitch(c, "night_cap")])


class EnabledSwitch(AdaptiveAudioEntity, SwitchEntity, RestoreEntity):
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.controller.enabled = last.state == STATE_ON

    @property
    def is_on(self) -> bool:
        return self.controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.controller.enabled = True
        self.controller.notify()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller.enabled = False
        self.controller.notify()


class QuietSwitch(AdaptiveAudioEntity, SwitchEntity, RestoreEntity):
    """Your own quiet switch. Quiet is also active while the linked entity is in its state;
    the `quiet_active` attribute shows the combined result."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.controller.quiet_switch = last.state == STATE_ON

    @property
    def is_on(self) -> bool:
        return self.controller.quiet_switch

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"quiet_active": self.controller.quiet_active}

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.controller.quiet_switch = True
        self.controller.quiet_changed()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller.quiet_switch = False
        self.controller.quiet_changed()


class AdaptSwitch(AdaptiveAudioEntity, SwitchEntity, RestoreEntity):
    """Adapt while playing: glide playing speakers along the curve. A hand change takes a
    speaker over until its next fresh start (or the auto-reset time)."""

    _attr_icon = "mdi:chart-bell-curve-cumulative"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.controller.adapt = last.state == STATE_ON

    @property
    def is_on(self) -> bool:
        return self.controller.adapt

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"taken_over": sorted(self.controller.manual)}

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.controller.adapt = True
        self.controller.manual.clear()
        self.controller.notify()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller.adapt = False
        self.controller.notify()


class CapSwitch(AdaptiveAudioEntity, SwitchEntity):
    """The night cap's own switch (the same setting as the toggle in Configure). The cap is
    also on while its linked entity is on; `cap_on` shows the combined result."""

    _attr_icon = "mdi:volume-minus"

    @property
    def is_on(self) -> bool:
        return bool(self.controller.opt(CONF_CAP_ENABLED))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"cap_on": self.controller.cap_on, "cap_active": self.controller.cap is not None}

    async def _set(self, on: bool) -> None:
        entry = self.controller.entry
        self.hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_CAP_ENABLED: on})
        self.controller.cap_changed()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
