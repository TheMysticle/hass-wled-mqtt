"""Config flow for WLED MQTT integration."""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_DEVICE_NAME,
    CONF_EFFECT_LIST,
    CONF_HOST,
    CONF_MQTT_BASE_TOPIC,
    CONF_NUM_SEGMENTS,
    CONF_DETECT_PRESETS,
    DEFAULT_EFFECT_LIST,
    DEFAULT_NUM_SEGMENTS,
    DEFAULT_DETECT_PRESETS,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_NAME): str,
        vol.Required(CONF_MQTT_BASE_TOPIC): str,
        vol.Optional(CONF_HOST, default=""): str,
        vol.Optional(CONF_NUM_SEGMENTS, default=DEFAULT_NUM_SEGMENTS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=16)
        ),
        vol.Optional(CONF_DETECT_PRESETS, default=DEFAULT_DETECT_PRESETS): bool,
    }
)


def _slugify(name: str) -> str:
    """Create a safe unique_id from a name."""
    return re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")


class WledMqttConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WLED MQTT."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input[CONF_DEVICE_NAME].strip()
            base_topic = user_input[CONF_MQTT_BASE_TOPIC].strip().rstrip("/")
            host = user_input.get(CONF_HOST, "").strip()
            detect_presets = user_input.get(CONF_DETECT_PRESETS, DEFAULT_DETECT_PRESETS)

            if not name:
                errors[CONF_DEVICE_NAME] = "name_empty"
            elif not base_topic:
                errors[CONF_MQTT_BASE_TOPIC] = "topic_empty"
            elif detect_presets and not host:
                errors[CONF_HOST] = "host_required_for_presets"
            else:
                unique_id = f"wled_mqtt_{_slugify(name)}_{_slugify(base_topic)}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_DEVICE_NAME: name,
                        CONF_MQTT_BASE_TOPIC: base_topic,
                        CONF_HOST: host,
                        CONF_NUM_SEGMENTS: user_input.get(CONF_NUM_SEGMENTS, DEFAULT_NUM_SEGMENTS),
                        CONF_DETECT_PRESETS: detect_presets,
                        CONF_EFFECT_LIST: DEFAULT_EFFECT_LIST,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            description_placeholders={
                "topic_hint": "e.g. wled/kitchen  ->  publishes to wled/kitchen, wled/kitchen/g, etc.",
                "host_hint": "Required only if preset detection is enabled. e.g. 192.168.1.50",
            },
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> WledMqttOptionsFlow:
        """Return the options flow."""
        return WledMqttOptionsFlow(config_entry)


class WledMqttOptionsFlow(config_entries.OptionsFlow):
    """Handle options (editing an existing entry)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            effects_raw = user_input.pop("effects_raw", "")
            effects_list = [
                e.strip() for e in effects_raw.split("\n") if e.strip()
            ] or DEFAULT_EFFECT_LIST

            return self.async_create_entry(
                title="",
                data={
                    **self._config_entry.data,
                    CONF_MQTT_BASE_TOPIC: user_input.get(
                        CONF_MQTT_BASE_TOPIC,
                        self._config_entry.data.get(CONF_MQTT_BASE_TOPIC, ""),
                    ),
                    CONF_HOST: user_input.get(
                        CONF_HOST,
                        self._config_entry.data.get(CONF_HOST, ""),
                    ),
                    CONF_NUM_SEGMENTS: user_input.get(
                        CONF_NUM_SEGMENTS,
                        self._config_entry.data.get(CONF_NUM_SEGMENTS, DEFAULT_NUM_SEGMENTS),
                    ),
                    CONF_DETECT_PRESETS: user_input.get(
                        CONF_DETECT_PRESETS,
                        self._config_entry.data.get(CONF_DETECT_PRESETS, DEFAULT_DETECT_PRESETS),
                    ),
                    CONF_EFFECT_LIST: effects_list,
                },
            )

        current_effects = self._config_entry.data.get(CONF_EFFECT_LIST, DEFAULT_EFFECT_LIST)
        effects_str = "\n".join(current_effects)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MQTT_BASE_TOPIC,
                    default=self._config_entry.data.get(CONF_MQTT_BASE_TOPIC, ""),
                ): str,
                vol.Optional(
                    CONF_HOST,
                    default=self._config_entry.data.get(CONF_HOST, ""),
                ): str,
                vol.Optional(
                    CONF_NUM_SEGMENTS,
                    default=self._config_entry.data.get(CONF_NUM_SEGMENTS, DEFAULT_NUM_SEGMENTS),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
                vol.Optional(
                    CONF_DETECT_PRESETS,
                    default=self._config_entry.data.get(CONF_DETECT_PRESETS, DEFAULT_DETECT_PRESETS),
                ): bool,
                vol.Optional(
                    "effects_raw",
                    default=effects_str,
                ): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
