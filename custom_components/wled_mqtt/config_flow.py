"""Config flow for WLED MQTT integration."""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_DEVICE_NAME, CONF_EFFECT_LIST, CONF_MQTT_BASE_TOPIC, CONF_PRESET_LIST, DEFAULT_EFFECT_LIST, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_NAME): str,
        vol.Required(CONF_MQTT_BASE_TOPIC): str,
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

            if not name:
                errors[CONF_DEVICE_NAME] = "name_empty"
            elif not base_topic:
                errors[CONF_MQTT_BASE_TOPIC] = "topic_empty"
            else:
                unique_id = f"wled_mqtt_{_slugify(name)}_{_slugify(base_topic)}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_DEVICE_NAME: name,
                        CONF_MQTT_BASE_TOPIC: base_topic,
                        CONF_EFFECT_LIST: DEFAULT_EFFECT_LIST,
                        CONF_PRESET_LIST: [],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            description_placeholders={
                "topic_hint": "e.g. wled/kitchen  →  publishes to wled/kitchen, wled/kitchen/g, etc."
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
        cfg = {**self._config_entry.data, **self._config_entry.options}

        if user_input is not None:
            # Parse effects
            effects_raw = user_input.pop("effects_raw", "")
            effects_list = [e.strip() for e in effects_raw.split("\n") if e.strip()] or DEFAULT_EFFECT_LIST

            # Parse presets — one per line, format "Name=ID"
            presets_raw = user_input.pop("presets_raw", "")
            preset_list = [p.strip() for p in presets_raw.split("\n") if p.strip() and "=" in p]

            return self.async_create_entry(
                title="",
                data={
                    CONF_MQTT_BASE_TOPIC: user_input.get(CONF_MQTT_BASE_TOPIC, cfg.get(CONF_MQTT_BASE_TOPIC, "")),
                    CONF_EFFECT_LIST: effects_list,
                    CONF_PRESET_LIST: preset_list,
                },
            )

        current_effects = cfg.get(CONF_EFFECT_LIST, DEFAULT_EFFECT_LIST)
        effects_str = "\n".join(current_effects)

        current_presets = cfg.get(CONF_PRESET_LIST, [])
        presets_str = "\n".join(current_presets)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MQTT_BASE_TOPIC,
                    default=cfg.get(CONF_MQTT_BASE_TOPIC, ""),
                ): str,
                vol.Optional(
                    "effects_raw",
                    default=effects_str,
                ): str,
                vol.Optional(
                    "presets_raw",
                    default=presets_str,
                ): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
