"""Quiet volume and cap volume. They are entry options too; changing them here saves the
option without reloading the instance."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CAP_VOLUME, CONF_QUIET_VOLUME
from .entity import AdaptiveVolumeEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    c = entry.runtime_data
    async_add_entities(
        [OptionNumber(c, "quiet_volume", CONF_QUIET_VOLUME), OptionNumber(c, "cap_volume", CONF_CAP_VOLUME)]
    )


class OptionNumber(AdaptiveVolumeEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, controller, key: str, option: str) -> None:
        super().__init__(controller, key)
        self._option = option

    @property
    def native_value(self) -> float:
        return float(self.controller.opt(self._option))

    async def async_set_native_value(self, value: float) -> None:
        entry = self.controller.entry
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, self._option: int(value)}
        )
        if self._option == CONF_QUIET_VOLUME:
            # A lower quiet volume applies at once to anything playing above it.
            self.controller._was_quiet = False
            self.controller.quiet_changed()
