"""Soporte de fan-coils FARNA y detección de familia de equipo.

Contexto (2026-08-24, PR #1 de @Jacketbg): los fan-coil FARNA usan una rama
distinta del protobuf que los aires. El PR detecta la familia leyendo la
respuesta de `get_state` y elige el campo de comando correcto al escribir
(3 = AC, 5 = fan-coil).

El riesgo del cambio es que `_parse_state` reescribe la ruta COMPARTIDA: los
aires que ya funcionaban dependen de ella. Estos tests fijan:

  1. Un aire se sigue decodificando igual (guarda de regresión).
  2. Un fan-coil se detecta por el campo 2 y no se confunde con un aire.
  3. El comando sale por el campo 3 o el 5 según la familia.
  4. Si la familia no se conoce, se consulta antes de mandar el comando.
  5. El RSSI negativo se decodifica con signo (int64 en complemento a dos).
  6. Una respuesta con forma DESCONOCIDA no se hace pasar por fan-coil apagado.

El (6) es el que motivó un arreglo: sin él, un equipo cuya respuesta no
entendemos aparecía en HA como "apagado, sin temperatura" en vez de
"no disponible", que es una mentira más cara que un error.
"""

import struct
from unittest.mock import AsyncMock

import pytest

from custom_components.innova_farna.api import (
    InnovaClient,
    InnovaDeviceOffline,
    _build_set_state,
    _fields,
    _ld,
    _one,
    _parse_state,
    _tag,
    _vint,
)


# ---------- constructores de fixtures (protobuf a mano) ----------

def _f32(field: int, value: float) -> bytes:
    """Campo float de 4 bytes (wire type 5), como los manda el equipo."""
    return _tag(field, 5) + struct.pack("<f", value)


def _bloque_estado(power=True, actual=22.5, target=24.0, modo=1, vel=2) -> bytes:
    tb = _f32(1, target) + _f32(2, 16.0) + _f32(3, 31.0) + _f32(4, 0.5)
    return (
        _vint(2, 1 if power else 0)
        + _ld(3, tb)
        + _ld(4, _vint(1, modo))
        + _ld(5, _vint(1, vel))
        + _f32(7, actual)
    )


def _respuesta(bloque: bytes | None, campo: int, rssi: int | None = None) -> bytes:
    """Arma la respuesta completa de get_state.

    `campo` es dónde cuelga el bloque de estado: 1 = aire, 2 = fan-coil.
    """
    s = _ld(campo, bloque) if bloque is not None else b""
    estado = _ld(2, _ld(2, s))

    metadata = b""
    if rssi is not None:
        crudo = rssi if rssi >= 0 else rssi + (1 << 64)
        metadata = _ld(4, _ld(2, _ld(1, _vint(2, crudo))))

    dispositivo = _ld(1, metadata) + estado
    return _ld(2, _ld(1, _ld(1, dispositivo)))


# ---------- 1. guarda de regresión: los aires siguen igual ----------

def test_un_aire_se_decodifica_igual_que_antes():
    st = _parse_state(_respuesta(_bloque_estado(), campo=1))
    assert st.family == "ac"
    assert st.power is True
    assert st.current_temperature == 22.5
    assert st.target_temperature == 24.0
    assert st.min_temp == 16.0
    assert st.max_temp == 31.0
    assert st.temp_step == 0.5
    assert st.hvac_mode == 1
    assert st.fan_speed == 2


# ---------- 2. detección de fan-coil ----------

def test_un_fancoil_se_detecta_por_el_campo_2():
    st = _parse_state(_respuesta(_bloque_estado(target=21.0), campo=2))
    assert st.family == "fancoil"
    assert st.target_temperature == 21.0
    assert st.power is True


def test_el_aire_gana_si_estan_los_dos_campos():
    """Ante ambigüedad se prefiere el aire: es el camino ya probado en producción."""
    s = _ld(1, _bloque_estado(target=24.0)) + _ld(2, _bloque_estado(target=18.0))
    resp = _ld(2, _ld(1, _ld(1, _ld(1, b"") + _ld(2, _ld(2, s)))))
    st = _parse_state(resp)
    assert st.family == "ac"
    assert st.target_temperature == 24.0


# ---------- 3. el comando sale por el campo correcto ----------

def test_el_comando_usa_campo_3_para_aire_y_5_para_fancoil():
    ss = _vint(1, 1)
    mac = "aa:bb:cc:dd:ee:ff"

    aire = _fields(_one(_fields(_build_set_state(mac, 0, ss, "ac")), 3))
    assert 3 in aire and 5 not in aire

    fan = _fields(_one(_fields(_build_set_state(mac, 0, ss, "fancoil")), 3))
    assert 5 in fan and 3 not in fan


def test_sin_familia_explicita_el_comando_asume_aire():
    """El default preserva el comportamiento previo al PR."""
    ss = _vint(1, 1)
    por_defecto = _build_set_state("aa:bb:cc:dd:ee:ff", 0, ss)
    explicito = _build_set_state("aa:bb:cc:dd:ee:ff", 0, ss, "ac")
    assert por_defecto == explicito


# ---------- 4. la familia se consulta si no se conoce ----------

async def test_set_state_consulta_la_familia_si_no_la_conoce():
    cli = InnovaClient(session=object())
    cli._send = AsyncMock(return_value=b"")
    cli.get_state = AsyncMock(
        side_effect=lambda mac, node=0: cli._device_families.__setitem__(
            (mac.lower(), node), "fancoil"
        )
    )

    await cli.set_state("AA:BB:CC:DD:EE:FF", node_id=0, power=True)

    cli.get_state.assert_awaited_once()
    enviado = cli._send.await_args[0][0]
    assert 5 in _fields(_one(_fields(enviado), 3)), "debió usar la rama fan-coil"


async def test_la_familia_conocida_no_gatilla_otra_consulta():
    cli = InnovaClient(session=object())
    cli._send = AsyncMock(return_value=b"")
    cli.get_state = AsyncMock()
    cli._device_families[("aa:bb:cc:dd:ee:ff", 0)] = "ac"

    await cli.set_state("AA:BB:CC:DD:EE:FF", node_id=0, power=True)

    cli.get_state.assert_not_awaited()


# ---------- 5. RSSI con signo ----------

def test_el_rssi_negativo_se_decodifica_con_signo():
    st = _parse_state(_respuesta(_bloque_estado(), campo=1, rssi=-62))
    assert st.wifi_rssi == -62


def test_sin_metadata_el_rssi_queda_en_none():
    st = _parse_state(_respuesta(_bloque_estado(), campo=1))
    assert st.wifi_rssi is None


# ---------- 6. una respuesta desconocida NO es un fan-coil apagado ----------

def test_respuesta_desconocida_no_se_hace_pasar_por_fancoil():
    """Sin bloque de estado en ningún campo, hay que fallar, no inventar.

    Antes del PR esto reventaba y `get_state` lo traducía a InnovaDeviceOffline.
    Con la detección por descarte, caía en la rama fan-coil con el bloque vacío
    y el equipo aparecía APAGADO Y SIN TEMPERATURA en Home Assistant — un estado
    plausible y falso, que es peor que un error visible.
    """
    with pytest.raises(Exception):
        _parse_state(_respuesta(None, campo=1))


# ---------- 7. el sensor de Wi-Fi no puede tumbar el termostato ----------
#
# Hallazgo de la revisión de Fable (2026-08-24): el parseo de RSSI recorre `d.f1`,
# un campo que el código anterior al PR nunca tocaba y cuya forma en un AIRE no
# está observada en vivo. Si llega con un wire type inesperado, `_fields(int)`
# revienta y el equipo queda "no disponible" en HA de forma permanente.

def _respuesta_metadata_rara(metadata_raw: bytes) -> bytes:
    """get_state válido para el clima, pero con metadata de forma inesperada."""
    estado = _ld(2, _ld(2, _ld(1, _bloque_estado(target=23.0))))
    return _ld(2, _ld(1, _ld(1, metadata_raw + estado)))


def test_metadata_como_varint_no_rompe_el_estado_climatico():
    """`d.f1` como entero en vez de submensaje: antes reventaba todo el parseo."""
    st = _parse_state(_respuesta_metadata_rara(_vint(1, 12345)))
    assert st.target_temperature == 23.0, "el clima debe parsearse igual"
    assert st.wifi_rssi is None, "el RSSI se rinde, no arrastra al resto"
    assert st.family == "ac"


def test_metadata_truncada_no_rompe_el_estado_climatico():
    st = _parse_state(_respuesta_metadata_rara(_ld(1, b"\xff\xff\xff")))
    assert st.target_temperature == 23.0
    assert st.wifi_rssi is None


# ---------- 8. hvac_mode de lectura discrimina por familia ----------
#
# `hvac_modes`, `fan_mode` y las escrituras ya miraban la familia; la propiedad de
# LECTURA `hvac_mode` no. Hoy los enteros coinciden, pero un fan-coil que reporte
# un modo fuera de su tabla mostraría un modo que su propia lista no ofrece.

def test_hvac_mode_de_lectura_usa_la_tabla_de_la_familia():
    from custom_components.innova_farna.const import (
        FARNA_HVAC_MODE_TO_HA,
        HVAC_MODE_TO_HA,
    )

    solo_ac = set(HVAC_MODE_TO_HA) - set(FARNA_HVAC_MODE_TO_HA)
    if not solo_ac:
        pytest.skip("las tablas coinciden: no hay valor que distinga las familias")

    crudo = next(iter(solo_ac))
    assert FARNA_HVAC_MODE_TO_HA.get(crudo) is None, (
        f"el modo {crudo} existe en AC pero no en FARNA: un fan-coil que lo "
        "reporte no debe mostrar el modo del aire"
    )


# ---------- 9. fallar visible en vez de mentir plausible ----------
#
# Hallazgos de la revisión de Grok (2026-08-24). Los tres comparten una causa:
# el parser prefería devolver un estado creíble antes que fallar. Un equipo que
# aparece "apagado y sin temperatura" es peor que uno "no disponible", porque
# nadie va a mirar dos veces un termostato que dice estar apagado.

def test_bloque_de_estado_presente_pero_vacio_no_pasa_por_apagado():
    """`b""` pasaba el `is not None` y salía AcState(power=False, temps=None).

    Este es el caso que el primer arreglo NO cubría: distinguía el campo AUSENTE
    del presente, pero no el presente-y-vacío.
    """
    s = _ld(1, b"")
    resp = _ld(2, _ld(1, _ld(1, _ld(1, b"") + _ld(2, _ld(2, s)))))
    with pytest.raises(Exception):
        _parse_state(resp)


def test_un_fancoil_gana_si_el_campo_del_aire_viene_vacio():
    """Campo 1 vacío no debe ganarle a un campo 2 con contenido real."""
    s = _ld(1, b"") + _ld(2, _bloque_estado(target=21.5))
    resp = _ld(2, _ld(1, _ld(1, _ld(1, b"") + _ld(2, _ld(2, s)))))
    st = _parse_state(resp)
    assert st.family == "fancoil"
    assert st.target_temperature == 21.5


def test_payload_truncado_no_se_lee_como_mensaje_vacio():
    """El slice de Python recorta en silencio; acá tiene que doler."""
    completo = _respuesta(_bloque_estado(), campo=1)
    with pytest.raises(Exception):
        _parse_state(completo[:-12])


def test_wire_type_desconocido_no_devuelve_estado_parcial():
    """Antes hacía `break` y entregaba lo decodificado hasta ese punto."""
    basura = _tag(9, 3) + b"\x01\x02"          # wire type 3 (grupo), no soportado
    resp = _respuesta(_bloque_estado() + basura, campo=1)
    with pytest.raises(Exception):
        _parse_state(resp)
