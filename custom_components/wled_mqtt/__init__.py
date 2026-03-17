"""WLED MQTT Integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

DOMAIN = "wled_mqtt"
PLATFORMS = ["light", "select"]


def get_config(entry: ConfigEntry) -> dict:
    """Return effective config, with options overriding data.

    HA stores initial values in entry.data and user edits in entry.options.
    They are never merged automatically, so we do it here. options wins on
    every key it contains, falling back to data for anything not yet edited.
    """
    return {**entry.data, **entry.options}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WLED MQTT from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a WLED MQTT config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
