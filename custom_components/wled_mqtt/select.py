"""WLED MQTT Select platform (segments and presets)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from homeassistant.components import mqtt
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import get_config
from .const import (
    CONF_DEVICE_NAME,
    CONF_DETECT_PRESETS,
    CONF_HOST,
    CONF_MQTT_BASE_TOPIC,
    CONF_NUM_SEGMENTS,
    DEFAULT_DETECT_PRESETS,
    DEFAULT_NUM_SEGMENTS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WLED MQTT select entities from a config entry."""
    data = get_config(config_entry)
    name = data[CONF_DEVICE_NAME]
    base_topic = data[CONF_MQTT_BASE_TOPIC]
    num_segments = data.get(CONF_NUM_SEGMENTS, DEFAULT_NUM_SEGMENTS)
    detect_presets = data.get(CONF_DETECT_PRESETS, DEFAULT_DETECT_PRESETS)
    host = data.get(CONF_HOST, "")

    entities: list[SelectEntity] = []
    segment_entity: WledSegmentSelect | None = None

    if num_segments > 1:
        segment_entity = WledSegmentSelect(
            hass,
            config_entry.entry_id,
            name,
            base_topic,
            num_segments,
        )
        entities.append(segment_entity)

    if detect_presets and host:
        entities.append(
            WledPresetSelect(
                hass,
                config_entry.entry_id,
                name,
                base_topic,
                host,
                segment_entity,
            )
        )

    if entities:
        async_add_entities(entities)


class WledSegmentSelect(SelectEntity):
    """Selector for the active WLED segment."""

    _attr_has_entity_name = True
    _attr_name = "Segment"
    _attr_icon = "mdi:led-strip-variant"

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        device_name: str,
        base_topic: str,
        num_segments: int,
    ) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._device_name = device_name
        self._cmd_topic = f"{base_topic}/api"
        self._attr_options = [f"Segment {i}" for i in range(num_segments)]
        self._attr_current_option = self._attr_options[0]
        self._attr_unique_id = f"wled_mqtt_segment_{entry_id}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=self._device_name,
            manufacturer="WLED",
            model="ESP32 WLED (MQTT)",
        )

    async def async_select_option(self, option: str) -> None:
        """Switch active segment via WLED JSON API over MQTT."""
        segment_idx = self._attr_options.index(option)
        # Build a JSON payload that selects only the chosen segment
        # sel:true = selected, sel:false = deselected for all others
        seg_payload = json.dumps({
            "seg": [
                {"id": i, "sel": i == segment_idx}
                for i in range(len(self._attr_options))
            ]
        })
        await mqtt.async_publish(self.hass, self._cmd_topic, seg_payload, 0, False)
        self._attr_current_option = option
        self.async_write_ha_state()

    def set_active_segment(self, segment_idx: int) -> None:
        """Called by WledPresetSelect to sync segment when a preset is applied."""
        if 0 <= segment_idx < len(self._attr_options):
            self._attr_current_option = self._attr_options[segment_idx]
            self.async_write_ha_state()


class WledPresetSelect(SelectEntity):
    """Selector for WLED presets, discovered via a one-shot HTTP fetch."""

    _attr_has_entity_name = True
    _attr_name = "Preset"
    _attr_icon = "mdi:palette"

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        device_name: str,
        base_topic: str,
        host: str,
        segment_entity: WledSegmentSelect | None,
    ) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._device_name = device_name
        self._host = host
        self._segment_entity = segment_entity

        # wled/<n>/api for commands, wled/<n>/ps for current preset ID state
        self._cmd_topic = f"{base_topic}/api"
        self._state_topic = f"{base_topic}/ps"

        # name -> id mapping, populated once from HTTP
        self._presets: dict[str, int] = {}
        # preset_id -> single segment index (only stored when preset targets exactly one segment)
        self._preset_segment: dict[int, int] = {}

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

    @property
    def options(self) -> list[str]:
        return list(self._presets.keys())

    async def async_added_to_hass(self) -> None:
        """Fetch preset list once over HTTP, then subscribe to MQTT state topic."""

        @callback
        def preset_state_received(msg: mqtt.ReceiveMessage) -> None:
            """Handle wled/<n>/ps — plain integer preset ID."""
            try:
                preset_id = int(str(msg.payload).strip())
            except ValueError:
                _LOGGER.debug("Could not parse preset state payload: %r", msg.payload)
                return

            # Update current option label
            for name, pid in self._presets.items():
                if pid == preset_id:
                    self._attr_current_option = name
                    break
            else:
                _LOGGER.debug("WLED ps: preset id=%d not in map, clearing selection", preset_id)
                self._attr_current_option = None

            # Sync segment selector if this preset targets a single segment
            if self._segment_entity and preset_id in self._preset_segment:
                self._segment_entity.set_active_segment(self._preset_segment[preset_id])

            self.async_write_ha_state()

        self._subscriptions.append(
            await mqtt.async_subscribe(self.hass, self._state_topic, preset_state_received, 0)
        )

        # One-shot HTTP fetch — runs once on startup/reload, never again
        self.hass.async_create_task(self._fetch_presets_once())

    async def _fetch_presets_once(self) -> None:
        """Fetch /presets.json from the WLED device exactly once."""
        url = f"http://{self._host}/presets.json"
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "WLED preset fetch returned HTTP %s for %s", resp.status, url
                    )
                    return
                # Read as text and parse manually — avoids aiohttp ContentTypeError
                # on WLED firmware that omits the Content-Type header
                raw = await resp.text()
        except asyncio.TimeoutError:
            _LOGGER.warning("Timed out fetching WLED presets from %s", url)
            return
        except aiohttp.ClientError as err:
            _LOGGER.warning("Error fetching WLED presets from %s: %s", url, err)
            return

        try:
            data: dict = json.loads(raw)
        except json.JSONDecodeError as err:
            _LOGGER.warning("Could not parse presets.json from %s: %s", url, err)
            return

        presets: dict[str, int] = {}
        preset_segment: dict[int, int] = {}

        for key, value in data.items():
            # Skip key "0" (WLED internal placeholder) and any non-dict entries
            if key == "0" or not isinstance(value, dict):
                continue
            try:
                preset_id = int(key)
            except ValueError:
                continue

            preset_name = value.get("n", f"Preset {preset_id}")

            # Skip auto-saved state snapshots — WLED names these "~ ... ~"
            if preset_name.startswith("~") and preset_name.endswith("~"):
                continue

            presets[preset_name] = preset_id

            # Determine if preset targets exactly one real segment.
            # WLED pads the seg array with stub entries like {"stop": 0} —
            # a real segment has a "start" key. Of those, count how many are "on".
            segs = value.get("seg")
            if isinstance(segs, list):
                real_segs = [s for s in segs if isinstance(s, dict) and "start" in s]
                active = [s.get("id", i) for i, s in enumerate(real_segs) if s.get("on", True)]
                if len(active) == 1:
                    preset_segment[preset_id] = active[0]

        self._presets = presets
        self._preset_segment = preset_segment
        _LOGGER.debug(
            "Loaded %d presets from %s (%d with single-segment mapping)",
            len(presets), self._host, len(preset_segment)
        )
        self.async_write_ha_state()

        # Now that the preset name->id map is ready, ask WLED to re-publish
        # its current state. Delay matches the light entity's startup delay so
        # WLED is ready to respond by the time we ask.
        await asyncio.sleep(3)
        await mqtt.async_publish(self.hass, self._cmd_topic, "v=1", 0, False)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from MQTT."""
        for unsub in self._subscriptions:
            unsub()

    async def async_select_option(self, option: str) -> None:
        """Apply a preset by ID."""
        if option not in self._presets:
            return
        preset_id = self._presets[option]
        await mqtt.async_publish(
            self.hass, self._cmd_topic, f"&PL={preset_id}", 0, False
        )
        self._attr_current_option = option
        self.async_write_ha_state()
