"""Siembra sin Excel: el checklist de los 151 y el espejo de su carta por
defecto (`sv03.5-{dex:03d}`) se generan desde `catalog.pokemon_151.los_151`,
no desde un archivo. Reejecutable y degradable, igual que el import viejo:
si TCGdex no responde para alguna carta, el checklist se siembra igual y esa
carta se salta -- nunca se aborta la corrida completa por una sola falla de
red.
"""

from contextlib import contextmanager

import httpx
import pytest

from pokedex.catalog.models import Card
from pokedex.catalog.service import CatalogService
from pokedex.wishlist import repository
from pokedex.wishlist.seed import SeedService


class FakeCatalogPort:
    """Puerto falso: resuelve los `card_id` en `cartas` con una `Card`
    mínima y devuelve `None` (respuesta real de "no existe") para el resto.
    """

    def __init__(self, cartas: set[str] | None = None):
        self._cartas = cartas or set()
        self.get_card_calls: list[str] = []

    async def get_card(self, card_id: str):
        self.get_card_calls.append(card_id)
        if card_id not in self._cartas:
            return None
        dex = card_id.removeprefix("sv03.5-")
        return Card(id=card_id, name="X", set_id="sv03.5", set_name="151", local_id=dex, raw={})

    async def find_by_set_and_number(self, set_id: str, local_id: str):
        raise AssertionError("la siembra no debería llamar a esto")

    async def list_set_cards(self, set_id: str):
        raise AssertionError("la siembra no debería llamar a esto")


class FakeCatalogPortSiempreFalla:
    """TCGdex completamente caído: toda consulta explota con un error de
    red, nunca con un 404/None."""

    def __init__(self):
        self.get_card_calls: list[str] = []

    async def get_card(self, card_id: str):
        self.get_card_calls.append(card_id)
        raise httpx.ConnectTimeout("catálogo caído (fake)")


class FakeCatalogPortConFallas:
    """Resuelve los `card_id` en `cartas`, explota para los de `fallan`
    (catálogo caído para esa carta puntual) y devuelve `None` real para el
    resto."""

    def __init__(self, cartas: set[str] | None = None, fallan: set[str] | None = None):
        self._cartas = cartas or set()
        self._fallan = fallan or set()

    async def get_card(self, card_id: str):
        if card_id in self._fallan:
            raise httpx.ConnectTimeout("catálogo caído (fake)")
        if card_id not in self._cartas:
            return None
        dex = card_id.removeprefix("sv03.5-")
        return Card(id=card_id, name="X", set_id="sv03.5", set_name="151", local_id=dex, raw={})


@pytest.fixture()
def conn_factory(clean_db):
    @contextmanager
    def factory():
        yield clean_db

    return factory


async def test_sembrar_crea_los_151_pokemon(conn_factory, clean_db):
    catalog = CatalogService(FakeCatalogPort(), conn_factory)
    resumen = await SeedService(catalog, conn_factory).sembrar()

    assert resumen.pokemon == 151
    filas = repository.list_pokedex(clean_db)
    assert len(filas) == 151
    assert filas[0]["name"] == "Bulbasaur"
    assert filas[-1]["name"] == "Mew"


async def test_sembrar_es_idempotente(conn_factory, clean_db):
    catalog = CatalogService(FakeCatalogPort(), conn_factory)
    service = SeedService(catalog, conn_factory)
    primero = await service.sembrar()
    segundo = await service.sembrar()

    assert primero.pokemon == segundo.pokemon == 151
    assert len(repository.list_pokedex(clean_db)) == 151


async def test_sembrar_espeja_la_carta_por_defecto_de_cada_pokemon(conn_factory, clean_db):
    port = FakeCatalogPort(cartas={f"sv03.5-{dex:03d}" for dex in range(1, 152)})
    catalog = CatalogService(port, conn_factory)
    resumen = await SeedService(catalog, conn_factory).sembrar()

    assert resumen.cartas_espejadas == 151
    assert resumen.catalogo_inalcanzable == 0
    espejadas = clean_db.execute(
        "select count(*) as n from app.card where id like 'sv03.5-%'"
    ).fetchone()["n"]
    assert espejadas == 151


async def test_sembrar_se_degrada_si_el_catalogo_esta_completamente_caido(conn_factory, clean_db):
    """El checklist se siembra igual aunque TCGdex no responda ni una vez."""
    catalog = CatalogService(FakeCatalogPortSiempreFalla(), conn_factory)
    resumen = await SeedService(catalog, conn_factory).sembrar()

    assert resumen.pokemon == 151, "la red caída no puede dejar el checklist vacío"
    assert resumen.cartas_espejadas == 0
    assert resumen.catalogo_inalcanzable == 151
    assert len(repository.list_pokedex(clean_db)) == 151


async def test_las_espejadas_y_las_inalcanzables_conviven(conn_factory, clean_db):
    port = FakeCatalogPortConFallas(cartas={"sv03.5-001", "sv03.5-002"}, fallan={"sv03.5-003"})
    catalog = CatalogService(port, conn_factory)
    resumen = await SeedService(catalog, conn_factory).sembrar()

    assert resumen.pokemon == 151
    assert resumen.cartas_espejadas == 2
    assert resumen.catalogo_inalcanzable == 1
    espejadas = clean_db.execute(
        "select count(*) as n from app.card where id like 'sv03.5-%'"
    ).fetchone()["n"]
    assert espejadas == 2


async def test_reintentar_despues_de_una_caida_completa_las_espeja(conn_factory, clean_db):
    """Recorre el camino de 'recuperación': la corrida que falló por
    completo no dejó nada a medias, y la siguiente, con el catálogo ya
    arriba, completa el espejo sin duplicar el checklist."""
    fallando = SeedService(
        CatalogService(FakeCatalogPortSiempreFalla(), conn_factory), conn_factory
    )
    primero = await fallando.sembrar()
    assert primero.cartas_espejadas == 0

    port = FakeCatalogPort(cartas={f"sv03.5-{dex:03d}" for dex in range(1, 152)})
    funcionando = SeedService(CatalogService(port, conn_factory), conn_factory)
    segundo = await funcionando.sembrar()

    assert segundo.pokemon == 151
    assert segundo.cartas_espejadas == 151
    assert len(repository.list_pokedex(clean_db)) == 151


async def test_reejecutar_no_vuelve_a_pedir_las_cartas_ya_espejadas(conn_factory, clean_db):
    """Segunda corrida: `CatalogService.get_card` sirve la copia local para
    las cartas ya espejadas, así que el puerto no debería recibir esa
    llamada de nuevo -- la siembra es barata de repetir (151 requests una
    sola vez, no en cada corrida)."""
    port = FakeCatalogPort(cartas={f"sv03.5-{dex:03d}" for dex in range(1, 152)})
    catalog = CatalogService(port, conn_factory)
    service = SeedService(catalog, conn_factory)
    await service.sembrar()
    assert len(port.get_card_calls) == 151

    await service.sembrar()
    assert len(port.get_card_calls) == 151, (
        "la segunda corrida no debe volver a pedir ninguna carta ya espejada"
    )
