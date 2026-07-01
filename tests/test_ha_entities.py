"""HA-side tests that need Home Assistant importable but no running hass.

Validates every sensor description's value_fn against an EbmxData built from a real
captured frame, and the cached-value display logic of EbmxSensor. Skipped automatically
when Home Assistant isn't installed (e.g. the pure-library test run).
"""

from __future__ import annotations

import pytest

pytest.importorskip("homeassistant")

from custom_components.ebmx import protocol, telemetry  # noqa: E402
from custom_components.ebmx.models import EbmxData  # noqa: E402
from custom_components.ebmx.sensor import SENSORS, EbmxSensor  # noqa: E402
from tests.fixtures_frames import GET_MCCONF_FRAME, GET_VALUES_FRAME_A  # noqa: E402


def _data() -> EbmxData:
    tpayload = next(iter(protocol.VescPacketizer().feed(GET_VALUES_FRAME_A)))
    cpayload = next(iter(protocol.VescPacketizer().feed(GET_MCCONF_FRAME)))
    t = telemetry.Telemetry.decode(tpayload)
    c = telemetry.McConfig.decode(cpayload)
    soc = telemetry.estimate_soc_percent(t.battery_voltage, c.inferred_cells, c)
    return EbmxData(telemetry=t, config=c, soc_estimate=soc)


def test_every_sensor_value_fn_runs() -> None:
    data = _data()
    values = {s.key: s.value_fn(data) for s in SENSORS}
    assert values["battery_voltage"] == pytest.approx(79.9, abs=0.05)
    assert values["battery_soc_controller"] == 86
    assert 75 <= values["battery_soc_estimate"] <= 90
    assert values["power"] == 0
    assert values["temp_fet"] == pytest.approx(33.0, abs=0.05)
    assert values["fault"] == 0
    # duty is scaled to a percentage
    assert values["duty_cycle"] == pytest.approx(0.0, abs=0.01)


def test_sensor_keys_unique() -> None:
    keys = [s.key for s in SENSORS]
    assert len(keys) == len(set(keys))


class _FakeCoordinator:
    """Duck-typed stand-in for the coordinator (no hass needed)."""

    def __init__(self, data: EbmxData | None) -> None:
        self.data = data
        self.address = "AA:BB:CC:DD:EE:FF"
        self.available = data is not None

    @property
    def device_info(self):  # pragma: no cover - not asserted here
        return None


def test_sensor_reads_live_value() -> None:
    coord = _FakeCoordinator(_data())
    desc = next(s for s in SENSORS if s.key == "battery_voltage")
    sensor = EbmxSensor(coord, desc)
    assert sensor.available is True
    assert sensor.native_value == pytest.approx(79.9, abs=0.05)
    assert sensor.unique_id == "AA:BB:CC:DD:EE:FF_battery_voltage"


def test_sensor_falls_back_to_restored_value_when_no_data() -> None:
    coord = _FakeCoordinator(None)
    desc = next(s for s in SENSORS if s.key == "battery_voltage")
    sensor = EbmxSensor(coord, desc)
    # Before any poll and with no restore, unavailable.
    assert sensor.available is False
    # Simulate a restored value from a previous HA session.
    sensor._restored_value = 79.5
    assert sensor.available is True
    assert sensor.native_value == 79.5


def test_live_value_supersedes_restored() -> None:
    coord = _FakeCoordinator(_data())
    desc = next(s for s in SENSORS if s.key == "battery_voltage")
    sensor = EbmxSensor(coord, desc)
    sensor._restored_value = 12.0
    # Live data present -> used regardless of restored value.
    assert sensor.native_value == pytest.approx(79.9, abs=0.05)
