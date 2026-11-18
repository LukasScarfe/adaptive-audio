"""Enabled and Quiet switches. Both restore their state across restarts."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import AdaptiveVolumeEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    c = entry.runtime_data
    async_add_entities([EnabledSwitch(c, "enabled"), QuietSwitch(c, "quiet"), AdaptSwitch(c, "adapt")])


class EnabledSwitch(AdaptiveVolumeEntity, SwitchEntity, RestoreEntity):
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


class QuietSwitch(AdaptiveVolumeEntity, SwitchEntity, RestoreEntity):
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


class AdaptSwitch(AdaptiveVolumeEntity, SwitchEntity, RestoreEntity):
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
