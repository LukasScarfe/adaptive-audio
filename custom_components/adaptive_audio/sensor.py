"""The target-volume sensor: what the schedule says now, plus everything the card plots."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CAP_ENABLED,
    CONF_CAP_ENTITY,
    CONF_CAP_VOLUME,
    CONF_CURVE,
    CONF_QUIET_VOLUME,
    CONF_SCHEDULE_TYPE,
    CURVE_SAMPLE_MINUTES,
)
from .entity import AdaptiveAudioEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    async_add_entities([TargetSensor(entry.runtime_data, "target")])


class TargetSensor(AdaptiveAudioEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:volume-vibrate"
    # The plot data changes rarely but is large; keep it out of the recorder.
    _unrecorded_attributes = frozenset({"curve", "curve_step", "marks", "cap_window", "last_applied"})

    @property
    def native_value(self) -> int | None:
        t = self.controller.target
        return None if t is None else int(round(t))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.controller
        cap_window = None
        if c.opt(CONF_CAP_ENABLED) or c.opt(CONF_CAP_ENTITY):
            cap_window = list(c.cap_window())
        return {
            "start_volume": c.start_volume,
            "schedule_type": c.opt(CONF_SCHEDULE_TYPE),
            "curve_type": c.opt(CONF_CURVE),
            "enabled": c.enabled,
            "adapt": c.adapt,
            "taken_over": sorted(c.manual),
            "quiet_active": c.quiet_active,
            "quiet_volume": c.opt(CONF_QUIET_VOLUME),
            "cap_on": c.cap_on,
            "cap_active": c.cap is not None,
            "cap": c.cap,
            "cap_volume": c.opt(CONF_CAP_VOLUME),
            "cap_window": cap_window,
            "players": c.players,
            "last_applied": c.last_applied,
            "schedule_error": c.schedule_error,
            "curve_step": CURVE_SAMPLE_MINUTES,
            "curve": c.curve_samples(),
            "marks": c.marks,
        }
