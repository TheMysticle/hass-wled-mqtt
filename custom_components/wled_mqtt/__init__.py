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

    Host is normalised to empty string if it looks invalid so stale garbage
    values from initial setup don't survive once options have been saved.
    """
    merged = {**entry.data, **entry.options}
    host = merged.get("host", "")
    if isinstance(host, str):
        host = host.strip()
        # Reject values with no dot or colon — not a valid IP or hostname
        if host and "." not in host and ":" not in host:
            host = ""
    merged["host"] = host
    return merged


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WLED MQTT from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a WLED MQTT config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
