"""Unit tests for telemetry/config decoding and the SOC estimate."""

from __future__ import annotations

import pytest

from custom_components.ebmx import protocol, telemetry
from tests.fixtures_frames import (
    GET_MCCONF_FRAME,
    GET_VALUES_FRAME_A,
    GET_VALUES_FRAME_B,
)


def _payload(frame: bytes) -> bytes:
    return next(iter(protocol.VescPacketizer().feed(frame)))


def test_decode_frame_a_battery_and_temps() -> None:
    t = telemetry.Telemetry.decode(_payload(GET_VALUES_FRAME_A))
    assert t is not None
    assert t.battery_voltage == pytest.approx(79.9, abs=0.05)
    assert t.controller_battery_percent == 86
    assert t.temp_fet == pytest.approx(33.0, abs=0.05)
    assert t.input_current == 0.0
    assert t.power_watts == 0.0
    assert t.rpm == 0
    assert t.fault == 0


def test_decode_frame_b_battery() -> None:
    t = telemetry.Telemetry.decode(_payload(GET_VALUES_FRAME_B))
    assert t is not None
    assert t.battery_voltage == pytest.approx(79.7, abs=0.05)
    assert t.controller_battery_percent == 85


def test_decode_has_full_field_set() -> None:
    t = telemetry.Telemetry.decode(_payload(GET_VALUES_FRAME_A))
    assert t is not None
    # Every field in the map should be present for a full-length payload.
    assert len(t.values) == len(telemetry.FIELDS)
    assert "batteryPercentage" in t.values
    assert "ODO" in t.values


def test_decode_rejects_wrong_command() -> None:
    assert telemetry.Telemetry.decode(bytes([0x99, 0x00, 0x00])) is None


def test_config_decode_signature_and_cutoffs() -> None:
    cfg = telemetry.McConfig.decode(_payload(GET_MCCONF_FRAME))
    assert cfg is not None
    assert cfg.signature == 0x968A9B08
    assert cfg.cut_start_volts == pytest.approx(61.4, abs=0.1)
    assert cfg.cut_end_volts == pytest.approx(60.0, abs=0.05)
    assert cfg.cut_plausible is True
    assert cfg.inferred_cells == 20  # 60.0 V / 3.0 V-per-cell


def test_soc_estimate_uses_inferred_cells() -> None:
    cfg = telemetry.McConfig.decode(_payload(GET_MCCONF_FRAME))
    assert cfg is not None
    soc = telemetry.estimate_soc_percent(79.7, cfg.inferred_cells, cfg)
    assert soc is not None
    # Between the dash's coulomb count (~78%) and the controller estimate (~85%).
    assert 75 <= soc <= 90


def test_soc_estimate_none_without_cells() -> None:
    assert telemetry.estimate_soc_percent(79.7, 0, None) is None
    assert telemetry.estimate_soc_percent(None, 20, None) is None


def test_soc_estimate_clamps() -> None:
    assert telemetry.estimate_soc_percent(84.0, 20, None) == 100.0
    assert telemetry.estimate_soc_percent(50.0, 20, None) == 0.0
