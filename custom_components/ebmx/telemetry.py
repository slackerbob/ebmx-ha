"""Decoding of EBMX X-Series telemetry and configuration payloads.

Pure standard-library code: no Home Assistant, no Bluetooth. All multi-byte values are
big-endian. Telemetry field offsets are transcribed verbatim from the RideControl app
asset xSeries_uart.json and are measured from the byte AFTER the command id.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import NamedTuple

from . import protocol


class Field(NamedTuple):
    """One field in a big-endian VESC payload (offset relative to after the cmd id)."""

    key: str
    offset: int
    length: int
    scale: float
    type: str  # "int" or "uint"


# Full COMM_GET_VALUES field map (from xSeries_uart.json).
FIELDS: tuple[Field, ...] = (
    Field("temp_fet_filtered", 0, 2, 10.0, "int"),
    Field("temp_motor_filtered", 2, 2, 10.0, "int"),
    Field("reset_avg_motor_current", 4, 4, 100.0, "int"),
    Field("reset_avg_input_current", 8, 4, 100.0, "int"),
    Field("reset_avg_id", 12, 4, 100.0, "int"),
    Field("reset_avg_iq", 16, 4, 100.0, "int"),
    Field("duty cycle", 20, 2, 1000.0, "int"),
    Field("rpm", 22, 4, 1.0, "int"),
    Field("Input_V", 26, 2, 10.0, "int"),
    Field("Battery Consumption", 28, 4, 10000.0, "int"),
    Field("Total Trip Time", 32, 4, 1.0, "uint"),
    Field("Total Watt Hour Draw", 36, 4, 10000.0, "int"),
    Field("6v Analog 3", 40, 4, 100.0, "int"),
    Field("Throttle", 44, 4, 100.0, "int"),
    Field("Regen", 48, 4, 100.0, "int"),
    Field("fault", 52, 1, 1.0, "uint"),
    Field("Digital_Inputs", 53, 1, 1.0, "uint"),
    Field("current_controller_id", 54, 1, 1.0, "uint"),
    Field("NTC_TEMP_MOS1", 55, 2, 10.0, "int"),
    Field("NTC_TEMP_MOS2", 57, 2, 10.0, "int"),
    Field("NTC_TEMP_MOS3", 59, 2, 10.0, "int"),
    Field("reset_avg_vd", 61, 4, 1000.0, "int"),
    Field("reset_avg_vq", 65, 4, 1000.0, "int"),
    Field("ODO", 72, 4, 1.0, "uint"),
    Field("6v Analog 4", 76, 4, 100.0, "int"),
    Field("Speed", 80, 4, 100.0, "int"),
    Field("Race/Street Mode", 84, 1, 1.0, "uint"),
    Field("Assist Level", 85, 1, 1.0, "int"),
    Field("voltage36v", 86, 4, 10000.0, "int"),
    Field("voltage5v5a", 90, 4, 10000.0, "int"),
    Field("temp36v", 94, 4, 10000.0, "int"),
    Field("temp5v5a", 98, 4, 10000.0, "int"),
    Field("voltage5vIn", 102, 4, 10000.0, "int"),
    Field("voltage5vExt", 106, 4, 10000.0, "int"),
    Field("voltage14v", 110, 4, 10000.0, "int"),
    Field("tempPcb", 114, 4, 10000.0, "int"),
    Field("tempBp", 118, 4, 10000.0, "int"),
    Field("io8", 122, 2, 1.0, "uint"),
    Field("ioBts", 124, 1, 1.0, "uint"),
    Field("currentBp", 125, 4, 10000.0, "int"),
    Field("hallA", 129, 1, 1.0, "uint"),
    Field("hallB", 130, 1, 1.0, "uint"),
    Field("hallCi", 131, 1, 1.0, "uint"),
    Field("pwm", 132, 1, 1.0, "uint"),
    Field("button", 133, 1, 1.0, "uint"),
    Field("throttle1", 134, 4, 100.0, "int"),
    Field("batteryPercentage", 138, 2, 1.0, "uint"),
    Field("throttleInPercentage", 140, 4, 1.0, "int"),
    Field("regenInPercentage", 144, 4, 1.0, "int"),
    Field("wheelieModeAngle", 148, 4, 100.0, "int"),
    Field("powerPercentage", 152, 2, 1.0, "uint"),
    Field("phaseCurrentOrTorquePercentage", 154, 2, 1.0, "int"),
)


def _read_be(data: bytes, offset: int, length: int, signed: bool) -> int:
    return int.from_bytes(data[offset : offset + length], "big", signed=signed)


@dataclass(frozen=True)
class Telemetry:
    """A decoded realtime telemetry sample: every reported field, plus helpers."""

    values: dict[str, float]

    def get(self, key: str) -> float | None:
        return self.values.get(key)

    # Curated accessors for the values worth surfacing as HA sensors.
    @property
    def battery_voltage(self) -> float | None:
        return self.values.get("Input_V")

    @property
    def controller_battery_percent(self) -> int | None:
        v = self.values.get("batteryPercentage")
        return int(v) if v is not None else None

    @property
    def motor_current(self) -> float | None:
        return self.values.get("reset_avg_motor_current")

    @property
    def input_current(self) -> float | None:
        return self.values.get("reset_avg_input_current")

    @property
    def power_watts(self) -> float | None:
        v, i = self.battery_voltage, self.input_current
        return None if v is None or i is None else v * i

    @property
    def duty_cycle(self) -> float | None:
        return self.values.get("duty cycle")

    @property
    def rpm(self) -> int | None:
        v = self.values.get("rpm")
        return int(v) if v is not None else None

    @property
    def speed_kph(self) -> float | None:
        return self.values.get("Speed")

    @property
    def temp_fet(self) -> float | None:
        return self.values.get("temp_fet_filtered")

    @property
    def temp_motor(self) -> float | None:
        return self.values.get("temp_motor_filtered")

    @property
    def throttle_percent(self) -> float | None:
        return self.values.get("throttleInPercentage")

    @property
    def fault(self) -> int | None:
        v = self.values.get("fault")
        return int(v) if v is not None else None

    @property
    def odometer(self) -> int | None:
        v = self.values.get("ODO")
        return int(v) if v is not None else None

    @classmethod
    def decode(cls, payload: bytes) -> "Telemetry | None":
        """Decode a GET_VALUES payload (payload[0] == command id). None if not applicable."""
        if not payload or payload[0] != protocol.COMM_GET_VALUES:
            return None
        data = payload[1:]
        values: dict[str, float] = {}
        for f in FIELDS:
            if f.offset + f.length > len(data):
                continue  # tolerate short payloads
            raw = _read_be(data, f.offset, f.length, f.type == "int")
            values[f.key] = raw if f.scale == 1.0 else raw / f.scale
        return cls(values) if values else None


@dataclass(frozen=True)
class McConfig:
    """Trustworthy static config from COMM_GET_MCCONF.

    NOTE: the config blob's byte layout is keyed to a firmware "signature" (its first 4
    bytes) and shifts between versions, so the app's bundled offsets for cell count / Ah
    are unreliable. What verifies against real hardware is the low-voltage cut-off pair
    (plain IEEE-754 BE floats near the start): on a 20S/74V pack they read 61.4/60.0 V,
    i.e. 3.0 V/cell at the end cut-off. We infer the series cell count from that.
    """

    signature: int
    cut_start_volts: float
    cut_end_volts: float
    cut_plausible: bool
    inferred_cells: int

    _OFF_CUT_START = 54
    _OFF_CUT_END = 58

    @classmethod
    def decode(cls, payload: bytes) -> "McConfig | None":
        if not payload or payload[0] != protocol.COMM_GET_MCCONF:
            return None
        data = payload[1:]
        if len(data) < cls._OFF_CUT_END + 4:
            return None
        signature = int.from_bytes(data[0:4], "big")
        cut_start = struct.unpack(">f", data[cls._OFF_CUT_START : cls._OFF_CUT_START + 4])[0]
        cut_end = struct.unpack(">f", data[cls._OFF_CUT_END : cls._OFF_CUT_END + 4])[0]
        plausible = 0 < cut_start < 400 and 0 < cut_end < 400 and cut_start >= cut_end
        cells = round(cut_end / 3.0) if plausible else 0
        return cls(signature, cut_start, cut_end, plausible, cells)


_FULL_VPC = 4.20
_DEFAULT_EMPTY_VPC = 3.30


def estimate_soc_percent(
    pack_voltage: float | None, cells: int, config: McConfig | None
) -> float | None:
    """Rough, transparent voltage-based SOC (0-100), or None if not computable.

    Linearly maps per-cell voltage between an "empty" point (the configured end cut-off
    per cell, when known) and 4.2 V/cell. A gauge, not a coulomb-counted reading.
    """
    if not pack_voltage or pack_voltage <= 0 or cells <= 0:
        return None
    v_cell = pack_voltage / cells
    if config is not None and config.cut_plausible:
        empty = min(max(config.cut_end_volts / cells, 2.8), 3.6)
    else:
        empty = _DEFAULT_EMPTY_VPC
    pct = (v_cell - empty) / (_FULL_VPC - empty) * 100.0
    return max(0.0, min(100.0, pct))


@dataclass(frozen=True)
class FirmwareInfo:
    """Installed firmware identity, decoded from a COMM_FW_VERSION response.

    The EBMX controller answers COMM_FW_VERSION with (in order) a couple of binary
    version bytes, the hardware name as an ASCII string (e.g. "X-9000 V3"), the firmware
    build as an 8-digit date string (e.g. "20260107"), and the STM32 serial/UUID. Rather
    than depend on exact offsets (which vary), we pull the printable-ASCII runs out of the
    payload: the first all-digit 8-char run is the version, the first non-numeric run is
    the hardware name. This mirrors what the official app logs ("s1=.., s2=..").
    """

    hardware: str | None
    version: str | None
    serial: str | None

    @classmethod
    def decode(cls, payload: bytes) -> "FirmwareInfo | None":
        if not payload or payload[0] != protocol.COMM_FW_VERSION:
            return None
        data = payload[1:]

        runs: list[str] = []
        cur = bytearray()
        for b in data:
            if 32 <= b < 127:
                cur.append(b)
            else:
                if len(cur) >= 2:
                    runs.append(cur.decode("ascii"))
                cur.clear()
        if len(cur) >= 2:
            runs.append(cur.decode("ascii"))

        version = next((r for r in runs if r.isdigit() and len(r) == 8), None)
        hardware = next((r for r in runs if not r.isdigit()), None)
        # Serial/UUID is the trailing binary block (commonly all 0xFF if unprogrammed).
        serial = data[-12:].hex() if len(data) >= 12 else None
        if hardware is None and version is None:
            return None
        return cls(hardware=hardware, version=version, serial=serial)
