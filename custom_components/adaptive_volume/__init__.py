"""Adaptive Volume: a time-of-day default volume for media players, like adaptive brightness."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import LIVE_OPTIONS
from .controller import AdaptiveVolumeController

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.SENSOR, Platform.NUMBER, Platform.BUTTON]

type AdaptiveVolumeConfigEntry = ConfigEntry[AdaptiveVolumeController]


async def async_setup_entry(hass: HomeAssistant, entry: AdaptiveVolumeConfigEntry) -> bool:
    controller = AdaptiveVolumeController(hass, entry)
    controller.loaded_options = dict(entry.options)
    entry.runtime_data = controller
    # Platforms first, so the switches restore enabled/quiet before players are watched.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    controller.async_start()
    entry.async_on_unload(controller.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: AdaptiveVolumeConfigEntry) -> None:
    """Reload on a settings change, but not when only a number entity moved."""
    controller = entry.runtime_data
    old, new = controller.loaded_options, dict(entry.options)
    changed = {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}
    if changed and not changed <= LIVE_OPTIONS:
        await hass.config_entries.async_reload(entry.entry_id)
        return
    controller.loaded_options = new
    controller.notify()


async def async_unload_entry(hass: HomeAssistant, entry: AdaptiveVolumeConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
