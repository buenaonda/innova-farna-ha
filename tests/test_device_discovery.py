"""Redescubrimiento automático de equipos nuevos en la cuenta Innova.

Contexto (2026-08-09): el coordinador pedía la lista de equipos UNA sola vez, al
montar la integración, y solo la repetía si había quedado vacía. Un aire
agregado a la cuenta después del setup no aparecía nunca — no tardaba, es que
nadie volvía a preguntar. Había que recargar la integración a mano.

Estos tests fijan las tres propiedades del arreglo:
  1. Se re-enumera cuando pasa DEVICE_REFRESH_INTERVAL, no en cada ciclo.
  2. Un equipo nuevo se detecta como nuevo.
  3. Si falla el redescubrimiento, los equipos que YA funcionaban siguen vivos.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from custom_components.innova_farna.api import Device, InnovaError
from custom_components.innova_farna.const import DEVICE_REFRESH_INTERVAL
from custom_components.innova_farna.coordinator import InnovaCoordinator


def _dev(mac: str, node: int = 0, nombre: str = "") -> Device:
    return Device(
        mac_address=mac,
        node_id=node,
        name=nombre or mac,
        serial_number=f"SN-{mac}",
        home_name="Casa",
        room_name=nombre or mac,
    )


@pytest.fixture
def coord() -> InnovaCoordinator:
    """Coordinador sin pasar por __init__, que exige un HomeAssistant real.

    Lo que se prueba acá es la lógica de redescubrimiento, que no depende de
    hass. Levantar todo el harness de HA para esto costaría mucho más de lo que
    aporta.
    """
    c = InnovaCoordinator.__new__(InnovaCoordinator)
    c.devices = []
    c._devices_refreshed_at = None
    c.client = AsyncMock()
    return c


class TestCuandoRedescubrir:
    def test_sin_equipos_toca_siempre(self, coord):
        assert coord._toca_redescubrir() is True

    def test_recien_refrescado_no_toca(self, coord):
        coord.devices = [_dev("aa")]
        coord._devices_refreshed_at = datetime.now(timezone.utc)
        assert coord._toca_redescubrir() is False

    def test_pasado_el_intervalo_toca(self, coord):
        coord.devices = [_dev("aa")]
        coord._devices_refreshed_at = (
            datetime.now(timezone.utc) - DEVICE_REFRESH_INTERVAL - timedelta(seconds=1)
        )
        assert coord._toca_redescubrir() is True

    def test_el_intervalo_es_mucho_mayor_que_el_de_estado(self):
        """Re-enumerar cada ciclo serían llamadas de más contra un tercero."""
        from custom_components.innova_farna.const import SCAN_INTERVAL

        assert DEVICE_REFRESH_INTERVAL >= SCAN_INTERVAL * 10


class TestDetectarNuevos:
    @pytest.mark.asyncio
    async def test_detecta_el_equipo_agregado(self, coord):
        coord.devices = [_dev("aa", nombre="Pieza")]
        coord._devices_refreshed_at = datetime.now(timezone.utc)
        coord.client.list_devices.return_value = [
            _dev("aa", nombre="Pieza"),
            _dev("bb", nombre="Sara"),
        ]

        nuevos = await coord._refresh_devices()

        assert [d.name for d in nuevos] == ["Sara"]
        assert len(coord.devices) == 2

    @pytest.mark.asyncio
    async def test_el_primer_arranque_no_los_llama_nuevos(self, coord):
        """Con la lista vacía, TODOS son 'nuevos' — anunciarlo sería ruido."""
        coord.client.list_devices.return_value = [_dev("aa"), _dev("bb")]

        nuevos = await coord._refresh_devices()

        # Se devuelven como nuevos (las plataformas los necesitan) pero el
        # coordinador no los reporta como novedad: no hay lista previa.
        assert len(nuevos) == 2
        assert len(coord.devices) == 2

    @pytest.mark.asyncio
    async def test_sin_cambios_no_hay_nuevos(self, coord):
        coord.devices = [_dev("aa")]
        coord.client.list_devices.return_value = [_dev("aa")]

        assert await coord._refresh_devices() == []

    @pytest.mark.asyncio
    async def test_actualiza_la_marca_de_tiempo(self, coord):
        coord.client.list_devices.return_value = [_dev("aa")]
        assert coord._devices_refreshed_at is None
        await coord._refresh_devices()
        assert coord._devices_refreshed_at is not None


class TestFallaDeRedescubrimiento:
    @pytest.mark.asyncio
    async def test_si_falla_listar_los_equipos_conocidos_siguen(self, coord):
        """La propiedad que más importa: que buscar equipos nuevos no pueda
        dejar sin estado a los que ya funcionaban."""
        coord.devices = [_dev("aa")]
        coord._devices_refreshed_at = (
            datetime.now(timezone.utc) - DEVICE_REFRESH_INTERVAL - timedelta(seconds=1)
        )
        coord.client.list_devices.side_effect = InnovaError("nube caída")
        coord.client.get_state.return_value = None

        estados = await coord._fetch_states()

        assert ("aa", 0) in estados
        assert len(coord.devices) == 1


async def test_una_lista_vacia_no_borra_los_equipos_vivos():
    """La nube puede responder 200 con `[]` en una falla transitoria.

    El `except InnovaError` solo cubre cuando la llamada LANZA. Con una lista
    vacía aceptada, `_fetch_states` devolvía un mapa vacío y TODAS las entidades
    caían, mientras el coordinador reportaba éxito: un fallo que no se ve como
    fallo. Hallazgo de la revisión de Grok (2026-08-24).
    """
    coord = InnovaCoordinator.__new__(InnovaCoordinator)
    coord.devices = [_dev("aa:bb:cc:dd:ee:01"), _dev("aa:bb:cc:dd:ee:02")]
    coord._devices_refreshed_at = None
    coord.client = AsyncMock()
    coord.client.list_devices = AsyncMock(return_value=[])

    nuevos = await coord._refresh_devices()

    assert nuevos == []
    assert len(coord.devices) == 2, "los equipos conocidos deben sobrevivir"
