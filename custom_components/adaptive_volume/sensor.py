"""The target-volume sensor: what the schedule says now, plus the full picture as attributes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MODE
from .entity import AdaptiveVolumeEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    async_add_entities([TargetSensor(entry.runtime_data, "target")])


class TargetSensor(AdaptiveVolumeEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:volume-vibrate"

    @property
    def native_value(self) -> int | None:
        t = self.controller.target
        return None if t is None else int(round(t))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.controller
        return {
            "start_volume": c.start_volume,
            "mode": c.opt(CONF_MODE),
            "quiet_active": c.quiet_active,
            "cap_active": c.cap is not None,
            "cap": c.cap,
            "enabled": c.enabled,
            "players": c.players,
            "last_applied": c.last_applied,
            "schedule_error": c.schedule_error,
        }
