"""Apply button: give every available speaker of the instance its start volume now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import AdaptiveAudioEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback):
    async_add_entities([ApplyButton(entry.runtime_data, "apply")])


class ApplyButton(AdaptiveAudioEntity, ButtonEntity):
    _attr_icon = "mdi:volume-check"

    async def async_press(self) -> None:
        await self.controller.async_apply_all()
