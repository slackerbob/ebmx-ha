"""Constants for the EBMX X-Series integration and library."""

from __future__ import annotations

DOMAIN = "ebmx"

# Nordic UART Service used by the EBMX X-Series controller.
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # app -> controller (write)
NUS_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # controller -> app (notify)

# How often to poll while the bike is present/advertising (seconds). Bikes are often on
# only briefly, so this is intentionally frequent.
POLL_INTERVAL_SECONDS = 10

# Config-entry option keys.
CONF_CELLS = "cells"  # optional series-cell override for the SOC estimate
