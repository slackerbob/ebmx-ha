"""Shared data model passed from the coordinator to entities."""

from __future__ import annotations

from dataclasses import dataclass

from .telemetry import McConfig, Telemetry


@dataclass
class EbmxData:
    """The latest poll result for one bike."""

    telemetry: Telemetry
    config: McConfig | None
    soc_estimate: float | None
