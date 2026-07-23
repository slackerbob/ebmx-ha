# EBMX X-Series — Home Assistant integration

A custom Home Assistant integration that reads live telemetry from an **EBMX X-Series
(X-9000)** e-bike motor controller over Bluetooth Low Energy, and a matching standalone
CLI for use without Home Assistant. It is fully self-contained — it does not depend on
the earlier C# tool or on any cloud service, and everything runs locally.

The controller is VESC-derived and speaks the VESC packet protocol over a Nordic UART
Service; this integration decodes that directly. See [Protocol](#protocol) below.

## Features

- **All the telemetry**, as individual sensors: battery voltage, two state-of-charge
  readings (the controller's own estimate and a transparent voltage-based one), input
  and motor current, power, speed, motor RPM, duty cycle, controller/motor temperature,
  throttle, odometer, and fault code.
- **One device per bike.** Add each bike separately; each becomes its own Home Assistant
  device with its own entities. Add as many as you like.
- **Uses Home Assistant's own Bluetooth stack**, so it works through any configured
  **Bluetooth proxy** (ESPHome, Shelly, etc.) transparently — no extra setup.
- **Polls only when the bike is present.** The integration watches for the bike's BLE
  advertisements and polls roughly every 10 seconds while it's on and in range; when the
  bike is off there are no advertisements and it simply doesn't poll. This suits a
  vehicle that's only powered on for short windows.
- **Keeps showing the last values when the bike is away.** The most recent reading stays
  on the dashboard (and survives Home Assistant restarts). A separate **Present**
  connectivity sensor tells you whether the bike is actually online right now.
- **Standalone CLI** that shares the exact same decoding code, for testing on a laptop.
- **Comprehensive tests** validated against real captured frames from a live bike.

## Installation

### Manual / HACS custom repository

1. Copy the `custom_components/ebmx` folder into your Home Assistant `config/custom_components/` directory (so you end up with `config/custom_components/ebmx/manifest.json`).
   *Or* add this repository to HACS as a custom repository (category: Integration) and install it.
2. Restart Home Assistant.
3. Your bike should be **discovered automatically** once it's powered on and within range
   of a Bluetooth adapter or proxy — look for a notification, or go to
   **Settings → Devices & Services** and add **EBMX X-Series** manually to pick it from
   the list of nearby devices.

No YAML configuration is required.

### Options

Each bike has one option: an optional **series cell count** override, used only for the
voltage-based SOC estimate. Leave it blank to infer it automatically from the
controller's voltage cut-off (see below). Set it via the device's **Configure** button.

## Entities

| Entity | Notes |
|---|---|
| Battery voltage | Pack voltage (V) |
| Battery (controller) | The controller's own SOC estimate (%) |
| Battery (estimate) | Rough voltage-based SOC (%); see caveat below |
| Input current / Motor current | Amps |
| Power | Volts × input current (W) |
| Speed | km/h |
| Motor RPM | |
| Duty cycle | % |
| Controller temperature | FET temperature (°C) |
| Motor temperature | °C — *disabled by default* (many bikes have no motor NTC) |
| Throttle | % |
| Odometer | km |
| Fault code | diagnostic |
| **Present** | connectivity binary sensor — on when the bike is advertising |

Measurement sensors keep displaying their last value when the bike is off; use the
**Present** sensor to tell whether a reading is live or cached.

## Standalone CLI (run without Home Assistant)

The same protocol/decoding code can run on its own — handy for testing. Install `bleak`
(the `cli` extra) and run it as a module from the repository root:

```bash
pip install bleak
python -m custom_components.ebmx.cli --scan                 # find bikes
python -m custom_components.ebmx.cli --address AA:BB:CC:DD:EE:FF
python -m custom_components.ebmx.cli --address AA:BB:CC:DD:EE:FF --json > telemetry.jsonl
python -m custom_components.ebmx.cli --address AA:BB:CC:DD:EE:FF --once --cells 20
```

With `--json`, one JSON object per sample is written to stdout (logs go to stderr).

## Testing

There are two layers of tests, both driven by real frames captured from a live bike.

**Pure library** (no Home Assistant, no Bluetooth needed) — the protocol, decoding,
config inference, SOC estimate, and the full client request/response pipeline (including
BLE fragmentation and interleaving):

```bash
pip install pytest pytest-asyncio
pytest            # ~33 tests; HA-only tests skip automatically
```

**Home Assistant integration tests** (config-flow discovery/dedupe and the coordinator
poll pipeline) run under the HA test harness:

```bash
pip install pytest-homeassistant-custom-component
pytest            # now also runs the HA tests
```

## Architecture

```
custom_components/ebmx/
  protocol.py     VESC CRC / framing / packet reassembly   (pure stdlib)
  telemetry.py    telemetry + config decode, SOC estimate  (pure stdlib)
  client.py       EbmxBleClient over a BleakClient-like     (no hard bleak import)
  models.py       EbmxData (what the coordinator produces)
  coordinator.py  ActiveBluetoothDataUpdateCoordinator      (HA + proxy-aware connect)
  entity.py       shared entity base
  sensor.py       all telemetry sensors (+ restore/caching)
  binary_sensor.py presence sensor
  config_flow.py  Bluetooth discovery + manual + options
  cli.py          standalone runner (uses bleak directly)
tests/            unit + integration tests + captured frames
```

The `protocol`, `telemetry`, `client`, `const`, and `models` modules import neither Home
Assistant nor bleak, which is what makes the library unit-testable and runnable
standalone. The coordinator uses Home Assistant's `ActiveBluetoothDataUpdateCoordinator`
(advertisement-driven polling with a built-in ~10 s cooldown) and
`bleak_retry_connector.establish_connection`, which routes through the best local adapter
or Bluetooth proxy automatically.

## Protocol

The X-9000 tunnels the **VESC** packet protocol over a Nordic UART Service
(`6e400001-…`). Telemetry comes from `COMM_GET_VALUES` (a 157-byte payload of ~52 fields);
static configuration from `COMM_GET_MCCONF`. All values are big-endian; packets are
framed with a length prefix and a CRC-16/XMODEM.

### Cell count and the SOC estimate — an honest caveat

The configuration blob's byte layout is keyed to a firmware **signature** and shifts
between firmware versions, so the app's own field offsets for cell count / capacity are
unreliable and can decode to nonsense. What *does* verify against real hardware is the
low-voltage cut-off near the start of the blob (plain IEEE-754 floats): on a 20S / 74 V
pack it reads **60.0 V**, i.e. exactly 3.0 V/cell. The integration therefore **infers the
series cell count** from that cut-off (`cells ≈ cut-off ÷ 3.0`), which is robust across
firmware, and you can override it in the options.

Three different battery percentages exist and won't match exactly: the bike dash uses the
OEM BMS's coulomb counting, the controller reports its own voltage estimate
(**Battery (controller)**), and this integration adds a simple, clearly-labelled
voltage-based estimate (**Battery (estimate)**). Voltage is the trustworthy number; treat
the estimate as a gauge, not a fuel reading.

## Firmware update entity

The integration adds an `update` entity per bike that mirrors the firmware-update check in
the official RideControl app. It reads the **installed** firmware from the controller
(VESC `COMM_FW_VERSION` → hardware name like `X-9000 V3` and an 8-digit build date like
`20260107`) and compares it against the **latest** published build in EBMX/CYC's public
manifest:

```
https://raw.githubusercontent.com/CYC-EBMX-Development/firmware/main/cyc/firmware.json
```

The controller's hardware name is matched to the most specific model key in the manifest
(e.g. `X-9000 V3` in preference to `X-9000`); the variant defaults to `Normal` and can be
changed per bike in the integration's options (for `B`/`MX` units). The manifest is
checked once at startup and daily thereafter.

**It is report-only by design.** It shows "update available" plus the version comparison
and a link to the firmware repo, but it does *not* flash anything — over-the-air VESC
bootloader flashing can brick a controller on a failed write, so that's left to the
official app. The `update` entity advertises no `INSTALL` feature, so Home Assistant shows
the status without an install button.

Verify the firmware read against your bike with the CLI:

```bash
python -m custom_components.ebmx.cli --address AA:BB:CC:DD:EE:FF --fw
# Installed: hardware='X-9000 V3' version='20260107' serial=ffffffffffffffffffffffff
# Latest:    model='X-9000 V3' variant='Normal' version='20260703'
# Update available: True
```
