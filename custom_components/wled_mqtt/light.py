"""WLED MQTT Light platform."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_NAME, CONF_EFFECT_LIST, CONF_MQTT_BASE_TOPIC, DEFAULT_EFFECT_LIST, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WLED MQTT light from a config entry."""
    data = config_entry.data
    name = data[CONF_DEVICE_NAME]
    base_topic = data[CONF_MQTT_BASE_TOPIC]
    effect_list = data.get(CONF_EFFECT_LIST, DEFAULT_EFFECT_LIST)

    async_add_entities([WledMqttLight(hass, config_entry.entry_id, name, base_topic, effect_list)])


class WledMqttLight(LightEntity):
    """Representation of a WLED light controlled via MQTT."""

    _attr_has_entity_name = True
    _attr_name = None  # uses device name as entity name

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        name: str,
        base_topic: str,
        effect_list: list[str],
    ) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._device_name = name
        self._base = base_topic
        self._effect_list = effect_list

        # Topics
        self._cmd_topic = base_topic                        # ON/OFF + brightness (WLED /win API)
        self._state_topic = f"{base_topic}/g"              # global brightness 0-255
        self._color_cmd_topic = f"{base_topic}/col"        # hex color
        self._color_state_topic = f"{base_topic}/c"        # hex color state
        self._effect_cmd_topic = f"{base_topic}/api"       # effect via WLED HTTP API syntax
        self._availability_topic = f"{base_topic}/status"  # online/offline

        # State
        self._is_on: bool = False
        self._brightness: int = 255
        self._rgb: tuple[int, int, int] = (255, 255, 255)
        self._effect: str | None = None
        self._available: bool = False

        self._attr_unique_id = f"wled_mqtt_{entry_id}"
        self._attr_supported_color_modes = {ColorMode.RGB}
        self._attr_color_mode = ColorMode.RGB
        self._attr_supported_features = LightEntityFeature.EFFECT

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._device_name,
            manufacturer="WLED",
            model="ESP32 WLED (MQTT)",
        )

    @property
    def available(self) -> bool:
        return self._available

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def brightness(self) -> int:
        return self._brightness

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        return self._rgb

    @property
    def effect(self) -> str | None:
        return self._effect

    @property
    def effect_list(self) -> list[str]:
        return self._effect_list

    async def async_added_to_hass(self) -> None:
        """Subscribe to MQTT topics when entity is added."""

        @callback
        def state_received(msg: mqtt.ReceiveMessage) -> None:
            """Handle brightness/state updates from wled/<n>/g."""
            try:
                val = int(msg.payload)
                self._is_on = val > 0
                self._brightness = val
            except ValueError:
                _LOGGER.warning("Unexpected state payload: %s", msg.payload)
            self.async_write_ha_state()

        @callback
        def color_received(msg: mqtt.ReceiveMessage) -> None:
            """Handle color updates from wled/<n>/c (hex: #RRGGBB)."""
            try:
                hex_color = str(msg.payload).strip()
                if hex_color.startswith("#") and len(hex_color) == 7:
                    r = int(hex_color[1:3], 16)
                    g = int(hex_color[3:5], 16)
                    b = int(hex_color[5:7], 16)
                    self._rgb = (r, g, b)
            except (ValueError, IndexError):
                _LOGGER.warning("Unexpected color payload: %s", msg.payload)
            self.async_write_ha_state()

        @callback
        def availability_received(msg: mqtt.ReceiveMessage) -> None:
            """Handle availability updates."""
            self._available = str(msg.payload).strip().lower() == "online"
            self.async_write_ha_state()

        self._subscriptions = [
            await mqtt.async_subscribe(self.hass, self._state_topic, state_received, 0),
            await mqtt.async_subscribe(self.hass, self._color_state_topic, color_received, 0),
            await mqtt.async_subscribe(self.hass, self._availability_topic, availability_received, 0),
        ]

        # Request WLED to re-publish its current state so HA reflects reality
        # after a restart. The "v=1" payload triggers WLED to broadcast all
        # state topics immediately. We delay briefly to ensure subscriptions
        # are active before the response arrives.
        async def _request_state() -> None:
            await asyncio.sleep(2)
            await mqtt.async_publish(self.hass, self._effect_cmd_topic, "v=1", 0, False)

        self.hass.async_create_task(_request_state())

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from MQTT topics."""
        for unsub in getattr(self, "_subscriptions", []):
            unsub()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on, optionally with brightness, color, or effect."""
        # Handle color first (independent topic)
        if ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            await mqtt.async_publish(self.hass, self._color_cmd_topic, hex_color, 0, True)
            self._rgb = (r, g, b)

        # Handle effect
        if ATTR_EFFECT in kwargs:
            effect_name = kwargs[ATTR_EFFECT]
            if effect_name in self._effect_list:
                effect_id = self._effect_list.index(effect_name)
                await mqtt.async_publish(
                    self.hass, self._effect_cmd_topic, f"&FX={effect_id}", 0, False
                )
                self._effect = effect_name

        # Handle brightness / turn on
        if ATTR_BRIGHTNESS in kwargs:
            # Explicit brightness requested — send it directly
            brightness = kwargs[ATTR_BRIGHTNESS]
            await mqtt.async_publish(self.hass, self._cmd_topic, str(brightness), 0, True)
            self._brightness = brightness
        else:
            # No brightness specified — use T=1 so WLED restores its own
            # last brightness and preset instead of forcing 255
            await mqtt.async_publish(self.hass, self._cmd_topic, "T=1", 0, False)

        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await mqtt.async_publish(self.hass, self._cmd_topic, "0", 0, True)
        self._is_on = False
        self.async_write_ha_state()