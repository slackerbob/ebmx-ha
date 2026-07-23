"""A thin async client that speaks the EBMX protocol over a connected GATT client.

It is written against a *structural* client interface (the subset of ``bleak``'s
``BleakClient`` we use), so it can be driven by a real Bleak client, by Home Assistant's
proxy-aware client, or by a fake in tests — without importing bleak here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from . import protocol
from .const import NUS_RX_CHAR_UUID, NUS_TX_CHAR_UUID
from .telemetry import FirmwareInfo, McConfig, Telemetry

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0


class BleakClientLike(Protocol):
	"""The subset of bleak.BleakClient used by :class:`EbmxBleClient`."""

	async def start_notify(self, char, callback) -> None: ...  # noqa: D102

	async def stop_notify(self, char) -> None: ...  # noqa: D102

	async def write_gatt_char(self, char, data, response: bool = ...) -> None: ...  # noqa: D102


class EbmxBleClient:
	"""Runs GET_VALUES / GET_MCCONF exchanges over a connected client.

	Usage::

			ebmx = EbmxBleClient(bleak_client)
			await ebmx.start()
			config = await ebmx.read_config()
			telemetry = await ebmx.read_values()
			await ebmx.stop()
	"""

	def __init__(self, client: BleakClientLike) -> None:
		self._client = client
		self._packetizer = protocol.VescPacketizer()
		# Decoded payloads waiting to be matched to a request, keyed by command id.
		self._waiters: dict[int, asyncio.Future[bytes]] = {}
		self._started = False

	async def start(self) -> None:
		"""Subscribe to controller notifications."""
		if self._started:
			_LOGGER.debug("EbmxBleClient.start called but client already started")
			return
		self._packetizer.reset()
		_LOGGER.debug("Starting notify on %s", NUS_TX_CHAR_UUID)
		await self._client.start_notify(NUS_TX_CHAR_UUID, self._on_notify)
		self._started = True
		_LOGGER.debug("Notify started")

	async def stop(self) -> None:
		if not self._started:
			_LOGGER.debug("EbmxBleClient.stop called but client not started")
			return
		try:
			_LOGGER.debug("Stopping notify on %s", NUS_TX_CHAR_UUID)
			await self._client.stop_notify(NUS_TX_CHAR_UUID)
		finally:
			self._started = False
			for fut in self._waiters.values():
				if not fut.done():
					fut.cancel()
			self._waiters.clear()
			_LOGGER.debug("Notify stopped and waiters cleared")

	def _on_notify(self, _char, data: bytearray) -> None:
		"""Notification callback: reassemble frames and hand them to any waiter."""
		_LOGGER.debug("RX notify len=%d", len(data))
		for payload in self._packetizer.feed(bytes(data)):
			cmd = payload[0]
			_LOGGER.debug("RX payload cmd=0x%02x len=%d", cmd, len(payload))
			fut = self._waiters.get(cmd)
			if fut is not None and not fut.done():
				fut.set_result(payload)
			else:
				_LOGGER.debug("No waiter for cmd=0x%02x", cmd)

	async def _request(self, frame: bytes, expect_cmd: int, timeout: float) -> bytes:
		"""Write ``frame`` and wait for a reassembled payload with ``expect_cmd``."""
		if not self._started:
			raise RuntimeError("call start() before issuing requests")
		loop = asyncio.get_running_loop()
		fut: asyncio.Future[bytes] = loop.create_future()
		self._waiters[expect_cmd] = fut
		try:
			_LOGGER.debug(
				"TX request expect_cmd=0x%02x len=%d timeout=%.1f frame=%s",
				expect_cmd,
				len(frame),
				timeout,
				frame.hex(),
			)
			# Write Without Response, mirroring the official app's high-rate polling.
			await self._client.write_gatt_char(NUS_RX_CHAR_UUID, frame, response=False)
			payload = await asyncio.wait_for(fut, timeout)
			_LOGGER.debug(
				"Request complete expect_cmd=0x%02x payload_len=%d",
				expect_cmd,
				len(payload),
			)
			return payload
		except Exception:
			_LOGGER.exception("Request failed expect_cmd=0x%02x", expect_cmd)
			raise
		finally:
			self._waiters.pop(expect_cmd, None)

	async def read_values(self, timeout: float = DEFAULT_TIMEOUT) -> Telemetry:
		"""Poll realtime telemetry (COMM_GET_VALUES)."""
		_LOGGER.debug("Issuing COMM_GET_VALUES")
		payload = await self._request(
			protocol.build_get_values_request(), protocol.COMM_GET_VALUES, timeout
		)
		telemetry = Telemetry.decode(payload)
		if telemetry is None:
			_LOGGER.debug("Failed to decode GET_VALUES payload: %s", payload.hex())
			raise ValueError("failed to decode GET_VALUES payload")
		_LOGGER.debug(
			"Decoded GET_VALUES voltage=%s controller_soc=%s rpm=%s",
			telemetry.battery_voltage,
			telemetry.controller_battery_percent,
			telemetry.rpm,
		)
		return telemetry

	async def read_config(self, timeout: float = DEFAULT_TIMEOUT) -> McConfig | None:
		"""Read static config once (COMM_GET_MCCONF). None if it doesn't answer/decode."""
		_LOGGER.debug("Issuing COMM_GET_MCCONF")
		try:
			payload = await self._request(
				protocol.build_get_mcconf_request(), protocol.COMM_GET_MCCONF, timeout
			)
		except (asyncio.TimeoutError, asyncio.CancelledError):
			_LOGGER.debug("No GET_MCCONF response; continuing without config")
			return None
		config = McConfig.decode(payload)
		if config is None:
			_LOGGER.debug("Failed to decode GET_MCCONF payload: %s", payload.hex())
		else:
			_LOGGER.debug(
				"Decoded GET_MCCONF sig=0x%08X cut=%.1f/%.1fV cells=%d plausible=%s",
				config.signature,
				config.cut_start_volts,
				config.cut_end_volts,
				config.inferred_cells,
				config.cut_plausible,
			)
		return config

	async def read_fw_version(self, timeout: float = DEFAULT_TIMEOUT) -> FirmwareInfo | None:
		"""Read the installed firmware identity (COMM_FW_VERSION). None if unavailable."""
		_LOGGER.debug("Issuing COMM_FW_VERSION")
		try:
			payload = await self._request(
				protocol.build_get_fw_version_request(), protocol.COMM_FW_VERSION, timeout
			)
		except (asyncio.TimeoutError, asyncio.CancelledError):
			_LOGGER.debug("No COMM_FW_VERSION response; firmware version unknown")
			return None
		info = FirmwareInfo.decode(payload)
		if info is None:
			_LOGGER.debug("Failed to decode COMM_FW_VERSION payload: %s", payload.hex())
		else:
			_LOGGER.debug("Firmware: hardware=%s version=%s serial=%s", info.hardware, info.version, info.serial)
		return info
