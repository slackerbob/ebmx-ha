"""Snapshot of the EBMX/CYC firmware manifest, embedded so tests need no external file.

Captured from https://raw.githubusercontent.com/CYC-EBMX-Development/firmware/main/cyc/firmware.json
"""

MANIFEST_JSON = r"""
{
  "X-9000": {
    "Normal": {
      "latest": "20250623",
      "url": "X-9000-TEST-SURRON-250623.bin",
      "md5": "1dcc29137ed56374ea04302353baca12"
    },
    "B": {
      "latest": "20250623",
      "url": "X-9000B-TEST-SURRON-250623.bin",
      "md5": "672e57b617d06588706da8349d87b63c"
    }
  },
  "X12 Pro Gen 3": {
    "Normal": {
      "latest": "20250604",
      "url": "X12-181-OQC-250604-PRO3.bin",
      "md5": "8b50347bd8b700ffd6aae8009ffefa54"
    }
  },
  "X12 Pro Gen 4": {
    "Normal": {
      "latest": "20250604",
      "url": "X12-181-OQC-250604-PRO4.bin",
      "md5": "1aee089037f856407a7968995e028a9e"
    },
    "MX": {
      "latest": "20250604",
      "url": "X12-181-OQC-250604-MXPRO4.bin",
      "md5": "e09b1a349a69eb33840dfbecfb52473b"
    },
    "RS": {
      "latest": "20240627",
      "url": "X12-181-RS-240627-PRO4.bin",
      "md5": "622122673d8b1e0638704d6849448268"
    }
  },
  "X6 - X1 Pro": {
    "Normal": {
      "latest": "20250604",
      "url": "X6-181-OQC-250604-PRO3.bin",
      "md5": "5e52ff311ac8cc37bcba0aaf30aadce5"
    }
  },
  "X6 - X1 Stealth": {
    "Normal": {
      "latest": "20250604",
      "url": "X6-181-OQC-250604-STL3.bin",
      "md5": "3d4bbe3837d5c7e3d53f3cdbbe9c8d1b"
    }
  },
  "Photon": {
    "BF": {
      "latest": "20240705",
      "url": "X6P-181-BFE-240705-PHN.bin",
      "md5": "b1c3ad322bc063061c8e98055e8b82bf"
    },
    "CO": {
      "latest": "20240314",
      "url": "X6P-181-CO-240314-PHN.bin",
      "md5": "903c75ef1730e9a13c384b73fa7d05dd"
    },
    "EP": {
      "latest": "20240827",
      "url": "X6P-181-EPAC_NO_SHOW_WATTAGE-240827-PHN.bin",
      "md5": "bba83606bec3ba05fea8c4907d85472f"
    },
    "JP": {
      "latest": "20240305",
      "url": "X6P-181-JAPAN-240305-PHN.bin",
      "md5": "bf11ef46ec7bed82206d908f7a9874ca"
    },
    "Normal": {
      "latest": "20250604",
      "url": "X6P-181-OQC-250604-PHN.bin",
      "md5": "88711a3e5da4e5e3813a693f59d58c82"
    }
  },
  "X-9000 V3": {
    "Normal": {
      "latest": "20260703",
      "url": "X9KV3_OQC_260703V01.bin",
      "md5": "facd86cc6456bdd05b304aa35103462c"
    }
  }
}
"""
