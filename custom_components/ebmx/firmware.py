"""Firmware update checking against the EBMX/CYC public firmware manifest.

The official RideControl app checks for updates by fetching a JSON manifest from a public
GitHub repository and comparing the ``latest`` build date it lists for the connected
model/variant against the firmware date read from the controller (COMM_FW_VERSION).

Manifest shape (``.../main/cyc/firmware.json``)::

    {
      "X-9000": {
        "Normal": {"latest": "20250623", "url": "X-9000-...-250623.bin", "md5": "..."},
        "B":      {"latest": "20250623", "url": "X-9000B-...-250623.bin", "md5": "..."}
      },
      "X12 Pro Gen 3": { ... },
      ...
    }

This module only *reads* the manifest and compares versions. It intentionally does NOT
flash anything: over-the-air VESC bootloader flashing is risky (a failed write can brick
the controller), so the Home Assistant integration surfaces availability only.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Public firmware host used by the RideControl app (found in the app's Dart library).
FIRMWARE_BASE_URL = "https://raw.githubusercontent.com/CYC-EBMX-Development/firmware/main/cyc/"
FIRMWARE_MANIFEST_URL = FIRMWARE_BASE_URL + "firmware.json"
# Human-facing page for "what changed / all files".
FIRMWARE_REPO_URL = "https://github.com/CYC-EBMX-Development/firmware/tree/main/cyc"

DEFAULT_MODEL = "X-9000"
DEFAULT_VARIANT = "Normal"


@dataclass(frozen=True)
class FirmwareRelease:
    """The latest published firmware for one model/variant."""

    model: str
    variant: str
    version: str  # 8-digit build date, e.g. "20250623"
    bin_url: str  # absolute URL to the .bin
    md5: str | None

    @property
    def release_url(self) -> str:
        return FIRMWARE_REPO_URL


def resolve_model_key(manifest: dict[str, Any], hardware: str | None) -> str | None:
    """Map a controller hardware name (e.g. "X-9000 V3") to a manifest model key.

    Returns the manifest key that is a prefix of the hardware name (case-insensitive),
    preferring the longest match, or None if nothing matches.
    """
    if not hardware:
        return None
    hw = hardware.strip().lower()
    best: str | None = None
    for key in manifest:
        if hw.startswith(key.lower()) and (best is None or len(key) > len(best)):
            best = key
    return best


def parse_manifest(
    raw: str | bytes,
    *,
    hardware: str | None = None,
    model: str | None = None,
    variant: str = DEFAULT_VARIANT,
) -> FirmwareRelease | None:
    """Parse a manifest and pick the release for the given model/variant.

    ``model`` wins if given; otherwise it's resolved from ``hardware``; otherwise the
    default model is used. Returns None if the model/variant isn't present.
    """
    try:
        manifest: dict[str, Any] = json.loads(raw)
    except (ValueError, TypeError) as err:
        _LOGGER.warning("Could not parse firmware manifest: %s", err)
        return None

    model_key = model or resolve_model_key(manifest, hardware) or DEFAULT_MODEL
    model_entry = manifest.get(model_key)
    if not isinstance(model_entry, dict):
        _LOGGER.debug("Model %s not in firmware manifest", model_key)
        return None

    variant_entry = model_entry.get(variant)
    if not isinstance(variant_entry, dict) and len(model_entry) == 1:
        # Only one variant published; use it whatever it's called.
        variant, variant_entry = next(iter(model_entry.items()))
    if not isinstance(variant_entry, dict):
        _LOGGER.debug("Variant %s not in firmware manifest for %s", variant, model_key)
        return None

    latest = variant_entry.get("latest")
    url = variant_entry.get("url")
    if not latest or not url:
        return None
    return FirmwareRelease(
        model=model_key,
        variant=variant,
        version=str(latest),
        bin_url=FIRMWARE_BASE_URL + str(url),
        md5=variant_entry.get("md5"),
    )


def is_update_available(installed: str | None, latest: str | None) -> bool:
    """True if ``latest`` is a newer build than ``installed``.

    Versions are 8-digit YYYYMMDD strings, so a numeric compare is chronological. If the
    installed version is unknown or non-standard, we conservatively report no update.
    """
    if not installed or not latest:
        return False
    if installed.isdigit() and latest.isdigit():
        return int(latest) > int(installed)
    return False
