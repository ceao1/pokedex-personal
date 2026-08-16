from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from pokedex.catalog.models import CardRef, SetRef
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import parse_card

from .loaders import load_fixture

CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


class FakeCatalog:
    """Fake del CatalogPort que cuenta las llamadas."""

    def __init__(
        self,
        cards: dict,
        set_cards: dict | None = None,
        sets: list[SetRef] | None = None,
        detalles: dict[str, SetRef] | None = None,
    ):
        self._cards = cards
        self._set_cards = set_cards or {}
        self._sets = sets or []
        self._detalles = detalles or {}
        self.get_card_calls = 0
        self.find_calls = 0
        self.list_set_cards_calls = 0
        self.list_sets_calls = 0
        self.get_set_detail_calls = 0

    async def get_card(self, card_id: str):
        self.get_card_calls += 1
        return self._cards.get(card_id)

    async def find_by_set_and_number(self, set_id: str, local_id: str):
        self.find_calls += 1
        for card in self._cards.values():
            if card.set_id == set_id and card.local_id == local_id:
                return card
        return None

    async def list_set_cards(self, set_id: str):
        self.list_set_cards_calls += 1
        return self._set_cards.get(set_id, [])

    async def list_sets(self):
        self.list_sets_calls += 1
        return self._sets

    async def get_set_detail(self, set_id: str):
        self.get_set_detail_calls += 1
        return self._detalles.get(set_id)


@pytest.fixture()
def conn_factory(clean_db):
    @contextmanager
    def factory():
        yield clean_db

    return factory


@pytest.fixture()
def bulbasaur():
    return parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)


async def test_la_primera_consulta_trae_de_tcgdex_y_espeja(conn_factory, bulbasaur, clean_db):
    fake = FakeCatalog({"sv03.5-001": bulbasaur})
    service = CatalogService(fake, conn_factory)

    card = await service.get_card("sv03.5-001")

    assert card.name == "Bulbasaur"
    assert fake.get_card_calls == 1
    guardadas = clean_db.execute("select count(*) as n from app.card").fetchone()["n"]
    assert guardadas == 1


async def test_la_segunda_consulta_no_toca_la_red(conn_factory, bulbasaur):
    fake = FakeCatalog({"sv03.5-001": bulbasaur})
    service = CatalogService(fake, conn_factory)

    await service.get_card("sv03.5-001")
    card = await service.get_card("sv03.5-001")

    assert card.name == "Bulbasaur"
    assert fake.get_card_calls == 1, "el espejo no evitó la segunda llamada"


async def test_una_carta_inexistente_devuelve_none(conn_factory):
    service = CatalogService(FakeCatalog({}), conn_factory)
    assert await service.get_card("no-existe") is None


async def test_find_by_set_and_number_tambien_espeja(conn_factory, bulbasaur, clean_db):
    fake = FakeCatalog({"sv03.5-001": bulbasaur})
    service = CatalogService(fake, conn_factory)

    await service.find_by_set_and_number("sv03.5", "001")
    card = await service.find_by_set_and_number("sv03.5", "001")

    assert card.id == "sv03.5-001"
    assert fake.find_calls == 1


async def test_list_set_cards_delega_al_puerto(conn_factory):
    fake = FakeCatalog({}, {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]})
    service = CatalogService(fake, conn_factory)

    refs = await service.list_set_cards("base1")

    assert [(r.id, r.local_id, r.name) for r in refs] == [("base1-4", "4", "Charizard")]
    assert fake.list_set_cards_calls == 1


async def test_list_set_cards_cachea_por_set(conn_factory):
    """Sin este cache el resolver dispararía una llamada de red por cada
    Pokémon vintage en vez de una por set."""
    fake = FakeCatalog({}, {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]})
    service = CatalogService(fake, conn_factory)

    await service.list_set_cards("base1")
    await service.list_set_cards("base1")

    assert fake.list_set_cards_calls == 1


async def test_list_set_cards_de_sets_distintos_no_comparte_cache(conn_factory):
    fake = FakeCatalog(
        {},
        {
            "base1": [CardRef(id="base1-4", local_id="4", name="Charizard")],
            "base2": [CardRef(id="base2-1", local_id="1", name="Clefable")],
        },
    )
    service = CatalogService(fake, conn_factory)

    await service.list_set_cards("base1")
    await service.list_set_cards("base2")

    assert fake.list_set_cards_calls == 2


# --- set_por_codigo / sets_por_total (catálogo sabe buscar por código y tamaño) ---

SET_ASCENDED = SetRef(id="me02.5", name="Ascended Heroes", total=217, abbreviation="ASC")
SET_BASE = SetRef(id="base1", name="Base Set", total=102)
SET_JUNGLE = SetRef(id="jungle", name="Jungle", total=102)


def _fake_con_sets(sets: list[SetRef], detalles: dict[str, SetRef]) -> FakeCatalog:
    return FakeCatalog({}, sets=sets, detalles=detalles)


async def test_set_por_codigo_encuentra_el_set(conn_factory):
    fake = _fake_con_sets([SET_ASCENDED], {"me02.5": SET_ASCENDED})
    service = CatalogService(fake, conn_factory)

    encontrado = await service.set_por_codigo("ASC")

    assert encontrado is not None
    assert encontrado.id == "me02.5"


async def test_set_por_codigo_no_distingue_mayusculas(conn_factory):
    fake = _fake_con_sets([SET_ASCENDED], {"me02.5": SET_ASCENDED})
    service = CatalogService(fake, conn_factory)

    assert (await service.set_por_codigo("asc")).id == "me02.5"


async def test_set_por_codigo_inexistente_devuelve_none(conn_factory):
    fake = _fake_con_sets([SET_ASCENDED], {"me02.5": SET_ASCENDED})
    service = CatalogService(fake, conn_factory)

    assert await service.set_por_codigo("ZZZ") is None


async def test_sets_por_total_devuelve_exactamente_uno(conn_factory):
    fake = _fake_con_sets([SET_ASCENDED, SET_BASE], {})
    service = CatalogService(fake, conn_factory)

    resultado = await service.sets_por_total(217)

    assert [s.id for s in resultado] == ["me02.5"]


async def test_sets_por_total_devuelve_varios_cuando_el_tamano_se_repite(conn_factory):
    fake = _fake_con_sets([SET_BASE, SET_JUNGLE], {})
    service = CatalogService(fake, conn_factory)

    resultado = await service.sets_por_total(102)

    assert {s.id for s in resultado} == {"base1", "jungle"}


async def test_set_por_codigo_pide_la_lista_una_sola_vez_aunque_se_consulten_varios_codigos(
    conn_factory,
):
    fake = _fake_con_sets(
        [SET_ASCENDED, SET_BASE], {"me02.5": SET_ASCENDED, "base1": SET_BASE.model_copy()}
    )
    service = CatalogService(fake, conn_factory)

    await service.set_por_codigo("ASC")
    await service.set_por_codigo("ZZZ")
    await service.sets_por_total(102)

    assert fake.list_sets_calls == 1, "la lista de 218 sets se pidió más de una vez"


async def test_set_por_codigo_no_reintenta_un_set_ya_resuelto_con_exito(conn_factory):
    """Una vez que el detalle de un set se trajo con éxito (tenga o no
    abreviatura), no vuelve a pedirse: solo los que fallaron de verdad (una
    excepción, no un `None` limpio) quedan pendientes para el próximo
    llamado."""

    class FakeConFalla(FakeCatalog):
        def __init__(self):
            super().__init__({}, sets=[SET_ASCENDED], detalles={"me02.5": SET_ASCENDED})
            self.fallar_una_vez = True

        async def get_set_detail(self, set_id: str):
            self.get_set_detail_calls += 1
            if self.fallar_una_vez:
                self.fallar_una_vez = False
                raise TimeoutError("502 simulado")
            return self._detalles.get(set_id)

    fake = FakeConFalla()
    service = CatalogService(fake, conn_factory)

    primero = await service.set_por_codigo("ASC")
    assert primero is None, "la primera vuelta falló, así que todavía no hay índice"

    segundo = await service.set_por_codigo("ASC")
    assert segundo is not None and segundo.id == "me02.5"
    assert fake.get_set_detail_calls == 2, "un intento por la falla, uno por el reintento"
