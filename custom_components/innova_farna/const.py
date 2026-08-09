"""Constants and enum mappings for the Innova FÄRNA integration."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.climate import HVACMode
from homeassistant.components.climate.const import FAN_AUTO, FAN_HIGH, FAN_LOW, FAN_MEDIUM

DOMAIN = "innova_farna"

# Polling interval. Changes made in the Innova app show up in HA within this
# window; commands sent from HA apply immediately. (A real-time SubscribeEvents
# push path is planned to make app-side changes instant.)
SCAN_INTERVAL = timedelta(seconds=15)

# Cada cuánto se vuelve a preguntar a la nube QUÉ EQUIPOS tiene la cuenta.
#
# Deliberadamente MUY superior a SCAN_INTERVAL: el estado de un aire cambia a
# cada rato, pero la lista de equipos de una cuenta cambia cuando alguien compra
# uno — cosa de meses. Re-enumerar en cada ciclo de 15 s serían 4 llamadas extra
# por minuto contra un servicio de terceros del que no conocemos el rate limit,
# a cambio de nada.
DEVICE_REFRESH_INTERVAL = timedelta(minutes=10)

MANUFACTURER = "Innova"

MIN_TEMP = 16.0
MAX_TEMP = 31.0
TARGET_TEMP_STEP = 0.5

FAN_MAX = "max"

# --- Enum mappings (numeric protobuf value -> HA), confirmed live -----------
HVAC_MODE_TO_HA: dict[int, HVACMode] = {
    1: HVACMode.AUTO,
    2: HVACMode.HEAT,
    3: HVACMode.COOL,
    4: HVACMode.DRY,
    5: HVACMode.FAN_ONLY,
}
HA_TO_HVAC_MODE: dict[HVACMode, int] = {v: k for k, v in HVAC_MODE_TO_HA.items()}

FAN_TO_HA: dict[int, str] = {
    1: FAN_AUTO,
    2: FAN_LOW,
    3: FAN_MEDIUM,
    4: FAN_HIGH,
    5: FAN_MAX,
}
HA_TO_FAN: dict[str, int] = {v: k for k, v in FAN_TO_HA.items()}
