"""HA-side tests for the firmware update entity (needs HA importable, no running hass)."""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from types import SimpleNamespace  # noqa: E402

from custom_components.ebmx.telemetry import FirmwareInfo  # noqa: E402
from custom_components.ebmx.update import EbmxFirmwareUpdate  # noqa: E402

from tests.fixture_firmware_manifest import MANIFEST_JSON as _MANIFEST


class _FakeCoordinator:
    def __init__(self, fw_info, options=None):
        self.fw_info = fw_info
        self.address = "AA:BB:CC:DD:EE:FF"
        self.entry = SimpleNamespace(options=options or {})
        self.last_update_success = True

    @property
    def device_info(self):
        return None


def _entity(fw_info, options=None) -> EbmxFirmwareUpdate:
    ent = EbmxFirmwareUpdate(_FakeCoordinator(fw_info, options))
    ent._manifest_raw = _MANIFEST
    return ent


def test_update_available_for_v3_bike() -> None:
    ent = _entity(FirmwareInfo(hardware="X-9000 V3", version="20260107", serial=None))
    assert ent.installed_version == "20260107"
    assert ent.latest_version == "20260703"  # newer build published for X-9000 V3
    assert ent.installed_version != ent.latest_version  # HA renders "update available"
    assert ent.title == "X-9000 V3 firmware"
    assert ent.available is True
    assert "20260703" in ent.release_summary
    assert ent.release_url.startswith("https://github.com/CYC-EBMX-Development/firmware")


def test_up_to_date_reports_equal_versions() -> None:
    ent = _entity(FirmwareInfo(hardware="X-9000 V3", version="20260703", serial=None))
    assert ent.installed_version == ent.latest_version == "20260703"


def test_no_manifest_falls_back_to_installed() -> None:
    ent = EbmxFirmwareUpdate(
        _FakeCoordinator(FirmwareInfo(hardware="X-9000 V3", version="20260107", serial=None))
    )
    # No manifest fetched yet -> don't claim an update.
    assert ent.latest_version == ent.installed_version == "20260107"


def test_variant_option_selects_b() -> None:
    ent = _entity(
        FirmwareInfo(hardware="X-9000", version="20250101", serial=None),
        options={"variant": "B"},
    )
    # X-9000/B exists in the manifest.
    assert ent.latest_version == "20250623"
    assert ent.installed_version != ent.latest_version


def test_unknown_firmware_hides_gracefully() -> None:
    ent = _entity(None)
    assert ent.installed_version is None
    assert ent.title == "EBMX firmware"
