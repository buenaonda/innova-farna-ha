"""Capturas REALES de aires en producción, como guarda de regresión.

Por qué existe (2026-08-24): la revisión de Fable señaló que los fixtures del
resto de la suite se construyen con las MISMAS suposiciones que el parser —
si el parser entiende mal el protocolo, los tests lo confirman en vez de
desmentirlo. Circular.

Estos bytes NO son inventados: salieron de `get_state` contra los dos aires que
funcionan en la casa (Studio y Sara, cuenta Innova real, 2026-08-24). Si un
cambio futuro rompe la decodificación de un equipo de verdad, esto lo detecta.

Cubren en particular la ruta de metadata (`d.f1`) que el PR #1 estrenó y que
nunca se había observado en un AIRE — solo deducida de un fan-coil.

Regenerar: ver tools/innova_cli.py y docs/PROTOCOL.md.
"""

from pathlib import Path

import pytest

from custom_components.innova_farna.api import _parse_state

FIXTURES = Path(__file__).parent / "fixtures"


def _cargar(nombre: str) -> bytes:
    return bytes.fromhex((FIXTURES / nombre).read_text().strip())


@pytest.mark.parametrize(
    "archivo,power,actual,target,modo,rssi",
    [
        ("get_state_ac_studio.hex", True, 23.7, 22.0, 2, -69),
        ("get_state_ac_sara.hex", False, 20.5, 22.5, 2, -81),
    ],
)
def test_captura_real_de_un_aire(archivo, power, actual, target, modo, rssi):
    st = _parse_state(_cargar(archivo))
    assert st.family == "ac", "un aire real NO debe detectarse como fan-coil"
    assert st.power is power
    assert st.current_temperature == actual
    assert st.target_temperature == target
    assert st.hvac_mode == modo
    assert st.wifi_rssi == rssi


def test_el_rssi_real_de_un_aire_es_plausible():
    """La ruta de metadata se dedujo de un fan-coil; acá se confirma en un AC.

    Un RSSI de Wi-Fi vive entre -100 y -30 dBm. Si el parseo estuviera leyendo
    el campo equivocado saldría un número absurdo, no un valor de esta banda.
    """
    for archivo in ("get_state_ac_studio.hex", "get_state_ac_sara.hex"):
        rssi = _parse_state(_cargar(archivo)).wifi_rssi
        assert rssi is not None
        assert -100 <= rssi <= -30, f"{archivo}: RSSI implausible ({rssi})"
