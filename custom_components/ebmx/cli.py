"""Standalone command-line runner — talk to a bike without Home Assistant.

This uses ``bleak`` directly (install with the ``cli`` extra) and shares the exact same
protocol/decoding code the Home Assistant integration uses, so it's ideal for testing on
a laptop or a headless box.

    python -m custom_components.ebmx.cli --scan
    python -m custom_components.ebmx.cli --address AA:BB:CC:DD:EE:FF [--json] [--once]
                                         [--interval 10] [--cells 20]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sys
from datetime import datetime, timezone

from .client import EbmxBleClient
from .firmware import FIRMWARE_MANIFEST_URL, is_update_available, parse_manifest
from .const import NUS_SERVICE_UUID
from .telemetry import McConfig, estimate_soc_percent

_LOGGER = logging.getLogger("ebmx.cli")


async def _scan() -> int:
    from bleak import BleakScanner

    print("Scanning 10 s for EBMX bikes (NUS service)...", file=sys.stderr)
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
    found = False
    for dev, adv in devices.values():
        if NUS_SERVICE_UUID.lower() in [u.lower() for u in adv.service_uuids]:
            found = True
            print(f"{dev.address}  {dev.name or '(unnamed)'}  rssi={adv.rssi}")
    if not found:
        print("No EBMX bikes found.", file=sys.stderr)
    return 0


async def _run(args: argparse.Namespace) -> int:
    from bleak import BleakClient

    config: McConfig | None = None
    while True:
        try:
            async with BleakClient(args.address, timeout=20.0) as client:
                ebmx = EbmxBleClient(client)
                await ebmx.start()
                if config is None:
                    config = await ebmx.read_config()
                    if config and config.cut_plausible:
                        _LOGGER.info(
                            "Config: sig=0x%08X cut=%.1f/%.1fV cells=%d",
                            config.signature, config.cut_start_volts,
                            config.cut_end_volts, config.inferred_cells,
                        )
                while True:
                    telemetry = await ebmx.read_values()
                    cells = args.cells or (config.inferred_cells if config else 0)
                    soc = estimate_soc_percent(telemetry.battery_voltage, cells, config)
                    if args.json:
                        _emit_json(telemetry, soc, cells, config)
                    else:
                        _emit_human(telemetry, soc)
                    if args.once:
                        return 0
                    await asyncio.sleep(args.interval)
        except asyncio.CancelledError:
            return 0
        except Exception as exc:  # noqa: BLE001
            if args.once:
                _LOGGER.error("Failed: %s", exc)
                return 1
            _LOGGER.warning("Connection lost/failed (%s); retrying in 2 s...", exc)
            await asyncio.sleep(2)


def _emit_human(t, soc) -> None:
    soc_est = f"{soc:.0f}%" if soc is not None else "n/a"
    _LOGGER.info(
        "V=%.1fV SOC(ctrl)=%s%% SOC(est)=%s | Iin=%.1fA Imot=%.1fA P=%.0fW | "
        "rpm=%s spd=%.1fkm/h | Tfet=%.1fC | fault=%s",
        t.battery_voltage, t.controller_battery_percent, soc_est,
        t.input_current or 0, t.motor_current or 0, t.power_watts or 0,
        t.rpm, t.speed_kph or 0, t.temp_fet or 0, t.fault,
    )


def _emit_json(t, soc, cells, config: McConfig | None) -> None:
    obj = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "voltage": t.battery_voltage,
        "socController": t.controller_battery_percent,
        "socEstimate": round(soc, 1) if soc is not None else None,
        "inputCurrentA": t.input_current,
        "motorCurrentA": t.motor_current,
        "powerW": t.power_watts,
        "rpm": t.rpm,
        "speedKph": t.speed_kph,
        "tempFetC": t.temp_fet,
        "tempMotorC": t.temp_motor,
        "fault": t.fault,
        "odometer": t.odometer,
        "config": None if config is None else {
            "cells": cells or None,
            "cutStartV": config.cut_start_volts if config.cut_plausible else None,
            "cutEndV": config.cut_end_volts if config.cut_plausible else None,
            "signature": f"0x{config.signature:08X}",
        },
        "raw": t.values,
    }
    print(json.dumps(obj))



async def _fw(args: argparse.Namespace) -> int:
    """Read the installed firmware version and compare with the published manifest."""
    import urllib.request
    from bleak import BleakClient

    async with BleakClient(args.address, timeout=20.0) as client:
        ebmx = EbmxBleClient(client)
        await ebmx.start()
        info = await ebmx.read_fw_version()
        await ebmx.stop()

    if info is None:
        print("Could not read firmware version from controller.", file=sys.stderr)
        return 1
    print(f"Installed: hardware={info.hardware!r} version={info.version!r} serial={info.serial}")

    try:
        raw = await asyncio.to_thread(
            lambda: urllib.request.urlopen(FIRMWARE_MANIFEST_URL, timeout=20).read().decode()
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Could not fetch firmware manifest: {exc}", file=sys.stderr)
        return 0

    release = parse_manifest(raw, hardware=info.hardware, variant=args.variant)
    if release is None:
        print("No matching model/variant in manifest.", file=sys.stderr)
        return 0
    available = is_update_available(info.version, release.version)
    print(f"Latest:    model={release.model!r} variant={release.variant!r} version={release.version!r}")
    print(f"Update available: {available}")
    if available:
        print(f"  {release.bin_url}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EBMX X-Series standalone reader")
    parser.add_argument("--address", help="Bike Bluetooth MAC address")
    parser.add_argument("--scan", action="store_true", help="Scan for bikes and exit")
    parser.add_argument("--fw", action="store_true", help="Read firmware version, check for update, and exit")
    parser.add_argument("--variant", default="Normal", help="Firmware variant to check (Normal/B/MX)")
    parser.add_argument("--json", action="store_true", help="Emit JSON lines on stdout")
    parser.add_argument("--once", action="store_true", help="Read one sample and exit")
    parser.add_argument("--interval", type=float, default=10.0, help="Poll interval (s)")
    parser.add_argument("--cells", type=int, default=0, help="Series cell-count override")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,  # keep stdout clean for --json
    )

    if args.scan:
        return asyncio.run(_scan())
    if args.fw:
        if not args.address:
            parser.error("--fw requires --address")
        return asyncio.run(_fw(args))
    if not args.address:
        parser.error("--address is required (or use --scan)")

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
