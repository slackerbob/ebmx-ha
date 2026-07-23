"""Tests for firmware version decoding and manifest comparison (pure, no HA)."""

from __future__ import annotations

from custom_components.ebmx import protocol
from custom_components.ebmx.firmware import (
    is_update_available,
    parse_manifest,
    resolve_model_key,
)
from custom_components.ebmx.telemetry import FirmwareInfo
from tests.fixture_firmware_manifest import MANIFEST_JSON as _MANIFEST


def _fw_frame(hardware: str, version: str, serial: bytes = b"\xff" * 12) -> bytes:
    """Build a COMM_FW_VERSION response like the controller sends."""
    payload = (
        bytes([protocol.COMM_FW_VERSION, 0x06, 0x00])  # cmd + (binary) major/minor
        + hardware.encode() + b"\x00"
        + version.encode() + b"\x00"
        + serial
    )
    return protocol.build_short_packet(payload)


def test_firmware_info_decodes_hardware_and_version() -> None:
    frame = _fw_frame("X-9000 V3", "20260107")
    payload = next(iter(protocol.VescPacketizer().feed(frame)))
    info = FirmwareInfo.decode(payload)
    assert info is not None
    assert info.hardware == "X-9000 V3"
    assert info.version == "20260107"
    assert info.serial == "ff" * 12


def test_firmware_info_survives_fragmentation() -> None:
    frame = _fw_frame("X-9000 V3", "20260107")
    pkt = protocol.VescPacketizer()
    payloads = []
    for i in range(0, len(frame), 7):  # tiny MTU
        payloads.extend(pkt.feed(frame[i : i + 7]))
    info = FirmwareInfo.decode(payloads[0])
    assert info.hardware == "X-9000 V3"
    assert info.version == "20260107"


def test_firmware_info_rejects_wrong_command() -> None:
    assert FirmwareInfo.decode(bytes([protocol.COMM_GET_VALUES, 1, 2, 3])) is None


def test_manifest_resolves_model_from_hardware() -> None:
    import json

    manifest = json.loads(_MANIFEST)
    # Most-specific prefix wins: "X-9000 V3" over "X-9000".
    assert resolve_model_key(manifest, "X-9000 V3") == "X-9000 V3"
    assert resolve_model_key(manifest, "X-9000") == "X-9000"
    assert resolve_model_key(manifest, "Totally Unknown") is None


def test_manifest_picks_latest_for_model() -> None:
    release = parse_manifest(_MANIFEST, hardware="X-9000 V3", variant="Normal")
    assert release is not None
    assert release.model == "X-9000 V3"
    assert release.variant == "Normal"
    assert release.version == "20260703"
    assert release.bin_url.startswith(
        "https://raw.githubusercontent.com/CYC-EBMX-Development/firmware/main/cyc/"
    )
    assert release.bin_url.endswith(".bin")
    assert release.md5


def test_manifest_variant_b() -> None:
    release = parse_manifest(_MANIFEST, model="X-9000", variant="B")
    assert release is not None and release.variant == "B"
    assert "9000B" in release.bin_url


def test_update_available_compares_dates() -> None:
    assert is_update_available("20250101", "20250623") is True
    assert is_update_available("20260107", "20250623") is False  # older manifest key
    assert is_update_available("20260107", "20260703") is True   # X-9000 V3: real update
    assert is_update_available("20250623", "20250623") is False
    assert is_update_available(None, "20250623") is False
    assert is_update_available("20250101", None) is False
