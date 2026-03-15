# WLED MQTT — Home Assistant Custom Integration

A HACS-compatible integration for controlling [WLED](https://kno.wled.ge/) devices via MQTT, **without using the official WLED integration**.

## Why does this exist?

The official WLED integration polls devices over HTTP, which can fill up internal buffers on ESP32s over time and make them unresponsive. This integration uses WLED's native MQTT support exclusively — no polling, pure push/subscribe.

## Features

- ✅ On/Off control
- ✅ Brightness
- ✅ RGB color
- ✅ Effects (full WLED effect list by index)
- ✅ Availability (online/offline via MQTT LWT)
- ✅ Config flow UI — no YAML needed
- ✅ Multiple devices, each added independently

## MQTT Topics Used

Given a base topic of `wled/kitchen`:

| Purpose | Topic |
|---|---|
| On/Off + Brightness command | `wled/kitchen` (payload: `0`–`255`) |
| Brightness state | `wled/kitchen/g` |
| Color command | `wled/kitchen/col` (payload: `#rrggbb`) |
| Color state | `wled/kitchen/c` |
| Effect command | `wled/kitchen/api` (payload: `&FX=<id>`) |
| Availability | `wled/kitchen/status` (`online` / `offline`) |

## WLED Configuration

In your WLED device settings, go to **Config → Sync Interfaces → MQTT** and set:

- **Broker**: your MQTT broker IP
- **Topic**: e.g. `wled/kitchen` ← this becomes the Base Topic in HA

## Installation

### Via HACS (recommended)

1. In HACS, go to **Integrations → Custom Repositories**
2. Add `https://github.com/themysticle/hass-wled-mqtt` as an **Integration**
3. Install **WLED MQTT**
4. Restart Home Assistant

### Manual

Copy the `custom_components/wled_mqtt` folder into your HA `config/custom_components/` directory and restart.

## Adding a Device

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **WLED MQTT**
3. Enter the device name and MQTT base topic
4. Done — a light entity appears immediately

## Effects

Effects are mapped by their WLED index (0 = Solid, 1 = Blink, etc.). The full built-in WLED effect list is included by default. If you have custom effects or a different WLED version, you can edit the effect list via the integration's **Options** flow.

## Requirements

- Home Assistant 2023.8.0+
- MQTT integration configured in Home Assistant
- WLED device with MQTT enabled
