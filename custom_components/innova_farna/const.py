"""Constants and enum mappings for the Innova FÄRNA integration."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.climate import HVACMode
from homeassistant.components.climate.const import FAN_AUTO, FAN_HIGH, FAN_LOW, FAN_MEDIUM

DOMAIN = "innova_farna"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_TOKEN = "token"

# Polling interval. The unit only answers while connected to the Innova cloud;
# the coordinator tolerates "device offline" between polls. Kept short so changes
# made in the Innova app show up in HA quickly (a real-time SubscribeEvents push
# path is planned to make this instant).
SCAN_INTERVAL = timedelta(seconds=15)

MANUFACTURER = "Innova"

MIN_TEMP = 16.0
MAX_TEMP = 31.0
TARGET_TEMP_STEP = 0.5

# --- Enum mappings ---------------------------------------------------------
# Confirmed live: the AC reports hvac_mode options [1,2,3,4,5] and fan_speed
# options [1,2,3,4,5]. The numeric->meaning mapping below is BEST-EFFORT
# (typical Innova order) and should be verified against the app; adjust here.
HVAC_MODE_TO_HA: dict[int, HVACMode] = {
    1: HVACMode.AUTO,       # confirmed live
    2: HVACMode.HEAT,       # confirmed live
    3: HVACMode.COOL,       # confirmed live
    4: HVACMode.DRY,        # confirmed live
    5: HVACMode.FAN_ONLY,   # confirmed live
}
HA_TO_HVAC_MODE: dict[HVACMode, int] = {v: k for k, v in HVAC_MODE_TO_HA.items()}

FAN_MAX = "max"
FAN_TO_HA: dict[int, str] = {
    1: FAN_AUTO,
    2: FAN_LOW,
    3: FAN_MEDIUM,
    4: FAN_HIGH,
    5: FAN_MAX,
}
HA_TO_FAN: dict[str, int] = {v: k for k, v in FAN_TO_HA.items()}
