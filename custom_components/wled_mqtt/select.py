"""WLED MQTT Select platform — preset selector."""
from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_NAME, CONF_MQTT_BASE_TOPIC, CONF_PRESET_LIST, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WLED MQTT select entities from a config entry."""
    data = {**config_entry.data, **config_entry.options}
    name = data[CONF_DEVICE_NAME]
    base_topic = data[CONF_MQTT_BASE_TOPIC]
    preset_list = data.get(CONF_PRESET_LIST, [])

    if preset_list:
        async_add_entities([
            WledPresetSelect(hass, config_entry.entry_id, name, base_topic, preset_list)
        ])


class WledPresetSelect(SelectEntity):
    """Preset selector for a WLED device.

    Presets are configured manually in the options flow (no HTTP fetching).
    Current preset is tracked via the wled/<n>/v MQTT topic which WLED
    publishes on every state change — contains XML with a <ps> element.
    Applying a preset sends &PL=<id> to wled/<n>/api.
    """

    _attr_has_entity_name = True
    _attr_name = "Preset"
    _attr_icon = "mdi:palette"

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        device_name: str,
        base_topic: str,
        preset_list: list[str],
    ) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._device_name = device_name

        # preset_list entries are "Name=ID" strings, e.g. "Music Mode=1"
        # Build a name->id map and a flat options list
        self._preset_map: dict[str, int] = {}
        for entry in preset_list:
            if "=" in entry:
                pname, _, pid_str = entry.partition("=")
                try:
                    self._preset_map[pname.strip()] = int(pid_str.strip())
                except ValueError:
                    pass

        self._cmd_topic = f"{base_topic}/api"
        self._v_topic = f"{base_topic}/v"

        self._attr_options = list(self._preset_map.keys())
        self._attr_current_option: str | None = None
        self._attr_unique_id = f"wled_mqtt_preset_{entry_id}"
        self._subscriptions: list = []

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._device_name,
            manufacturer="WLED",
            model="ESP32 WLED (MQTT)",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to wled/<n>/v for real-time preset state tracking."""

        @callback
        def v_received(msg: mqtt.ReceiveMessage) -> None:
            """Parse XML published by WLED on every state change.

            WLED publishes the full /win API XML response to wled/<n>/v on
            every light change. The <ps> element contains the active preset
            ID, or 65535 when no preset is active.
            """
            try:
                root = ET.fromstring(str(msg.payload).strip())
                ps_el = root.find("ps")
                if ps_el is None or not ps_el.text:
                    return
                preset_id = int(ps_el.text)
            except (ET.ParseError, ValueError):
                _LOGGER.debug("Could not parse WLED /v XML payload")
                return

            # 65535 (0xFFFF) means no preset active
            if preset_id == 65535 or preset_id == 0:
                self._attr_current_option = None
            else:
                for name, pid in self._preset_map.items():
                    if pid == preset_id:
                        self._attr_current_option = name
                        break
                else:
                    self._attr_current_option = None

            self.async_write_ha_state()

        self._subscriptions.append(
            await mqtt.async_subscribe(self.hass, self._v_topic, v_received, 0)
        )

        # Ask WLED to publish its current state immediately so we don't show
        # "unknown" until the next natural state change. The v=1 command
        # triggers WLED to broadcast to /v right away.
        async def _request_state() -> None:
            await asyncio.sleep(2)
            await mqtt.async_publish(self.hass, self._cmd_topic, "v=1", 0, False)

        self.hass.async_create_task(_request_state())

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from MQTT."""
        for unsub in self._subscriptions:
            unsub()

    async def async_select_option(self, option: str) -> None:
        """Apply a preset by sending &PL=<id> to the WLED API topic."""
        if option not in self._preset_map:
            return
        preset_id = self._preset_map[option]
        await mqtt.async_publish(
            self.hass, self._cmd_topic, f"&PL={preset_id}", 0, False
        )
        self._attr_current_option = option
        self.async_write_ha_state()
