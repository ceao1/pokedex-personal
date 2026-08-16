from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from pokedex.catalog.models import CardRef, SetRef
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import parse_card
from pokedex.recognition.models import Recognition
from pokedex.recognition.resolver import CardResolver

from ..catalog.loaders import load_fixture

CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

SET_BASE = SetRef(id="base1", name="Base Set", total=102)
SET_ASCENDED = SetRef(id="me02.5", name="Ascended Heroes", total=30)

GLOOM_CARD_ID = "me02.5-002"


class FakeCatalog:
    """Fake del CatalogPort: solo lo que `CardResolver` realmente llama."""

    def __init__(self, cards: dict, set_cards: dict, sets: list[SetRef]):
        self._cards = cards
        self._set_cards = set_cards
        self._sets = sets

    async def get_card(self, card_id: str):
        return self._cards.get(card_id)

    async def find_by_set_and_number(self, set_id: str, local_id: str):
        raise NotImplementedError("CardResolver no usa este método")

    async def list_set_cards(self, set_id: str):
        return self._set_cards.get(set_id, [])

    async def list_sets(self):
        return self._sets


@pytest.fixture()
def conn_factory(clean_db):
    @contextmanager
    def factory():
        yield clean_db

    return factory


@pytest.fixture()
def charizard():
    """Ya trae `dex_number=6` de TCGdex (dexId real)."""
    return parse_card(load_fixture("card_base1-4"), CAPTURED_AT)


@pytest.fixture()
def gloom_sin_dex():
    """ "Erika's Gloom" de Ascended Heroes: TCGdex no trae `dexId` para las
    cartas de entrenador, así que `dex_number` nace en `None`."""
    return parse_card(
        {
            "id": GLOOM_CARD_ID,
            "name": "Erika's Gloom",
            "localId": "002",
            "set": {"id": "me02.5", "name": "Ascended Heroes", "cardCount": {"official": 30}},
            "rarity": "Uncommon",
            "image": "https://x/gloom",
            "variants_detailed": [],
        },
        CAPTURED_AT,
    )


def _resolver(cards: dict, set_cards: dict, sets: list[SetRef], conn_factory) -> CardResolver:
    fake = FakeCatalog(cards, set_cards, sets)
    return CardResolver(CatalogService(fake, conn_factory), conn_factory)


def _reconocido(**overrides) -> Recognition:
    base = dict(
        name="Charizard",
        set_name="Base Set",
        number="4/102",
        rarity="Rare Holo",
        species=None,
        dex_number=None,
        confidence=0.95,
        needs_review=False,
    )
    base.update(overrides)
    return Recognition(**base)


# --- Resolución básica por set + número (casos 1-9 del plan) -------------


async def test_resuelve_por_set_y_numero(conn_factory, charizard):
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido())
    assert resolucion.card is not None
    assert resolucion.card.id == "base1-4"
    assert resolucion.necesita_revision is False


async def test_numero_con_ceros_normaliza(conn_factory, charizard):
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(number="004/102"))
    assert resolucion.card is not None and resolucion.card.id == "base1-4"


async def test_set_name_en_minusculas(conn_factory, charizard):
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(set_name="base set"))
    assert resolucion.card is not None and resolucion.card.id == "base1-4"


async def test_set_inexistente(conn_factory):
    resolver = _resolver({}, {}, [SET_BASE], conn_factory)
    resolucion = await resolver.resolver(_reconocido(set_name="Set Que No Existe"))
    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert "no existe" in resolucion.motivo


async def test_denominador_no_cuadra_con_el_cardcount(conn_factory):
    resolver = _resolver(
        {},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(number="4/999"))
    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert "contradijo" in resolucion.motivo


async def test_numero_inexistente_en_el_set(conn_factory):
    resolver = _resolver(
        {},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(number="55/102"))
    assert resolucion.card is None
    assert resolucion.necesita_revision is True


async def test_needs_review_del_modelo_gana_aunque_todo_lo_demas_resuelva(conn_factory, charizard):
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(needs_review=True))
    assert resolucion.card is None
    assert resolucion.necesita_revision is True


async def test_confianza_baja_gana_aunque_todo_lo_demas_resuelva(conn_factory, charizard):
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(confidence=0.5))
    assert resolucion.card is None
    assert resolucion.necesita_revision is True


async def test_nombre_no_coincide_con_la_carta_encontrada(conn_factory, charizard):
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(name="Squirtle"))
    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert "contradictorias" in resolucion.motivo


# --- Especie/dex_number para cartas sin dexId (Erika's X, etc.) -----------


async def test_especie_valida_infiere_dex_number(conn_factory, clean_db, gloom_sin_dex):
    clean_db.execute(
        "insert into app.pokemon (dex_number, name) values (44, 'Gloom'), (45, 'Vileplume')"
    )
    resolver = _resolver(
        {GLOOM_CARD_ID: gloom_sin_dex},
        {"me02.5": [CardRef(id=GLOOM_CARD_ID, local_id="002", name="Erika's Gloom")]},
        [SET_ASCENDED],
        conn_factory,
    )
    reconocido = _reconocido(
        name="Erika's Gloom",
        set_name="Ascended Heroes",
        number="2/30",
        species="Gloom",
        dex_number=44,
    )
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.necesita_revision is False
    assert resolucion.card is not None
    assert resolucion.card.dex_number == 44
    assert resolucion.card.dex_number_inferido is True


async def test_especie_contradice_app_pokemon_no_adivina(conn_factory, clean_db, gloom_sin_dex):
    clean_db.execute(
        "insert into app.pokemon (dex_number, name) values (44, 'Gloom'), (45, 'Vileplume')"
    )
    resolver = _resolver(
        {GLOOM_CARD_ID: gloom_sin_dex},
        {"me02.5": [CardRef(id=GLOOM_CARD_ID, local_id="002", name="Erika's Gloom")]},
        [SET_ASCENDED],
        conn_factory,
    )
    reconocido = _reconocido(
        name="Erika's Gloom",
        set_name="Ascended Heroes",
        number="2/30",
        species="Vileplume",
        dex_number=44,
    )
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert "contradictorias" in resolucion.motivo


async def test_dex_number_fuera_de_151_no_se_infiere_ni_se_marca(conn_factory, gloom_sin_dex):
    resolver = _resolver(
        {GLOOM_CARD_ID: gloom_sin_dex},
        {"me02.5": [CardRef(id=GLOOM_CARD_ID, local_id="002", name="Erika's Gloom")]},
        [SET_ASCENDED],
        conn_factory,
    )
    reconocido = _reconocido(
        name="Erika's Gloom",
        set_name="Ascended Heroes",
        number="2/30",
        species="Chikorita",
        dex_number=152,
    )
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.necesita_revision is False
    assert resolucion.card is not None
    assert resolucion.card.dex_number is None
    assert resolucion.card.dex_number_inferido is False


async def test_entrenador_sin_especie_es_resultado_normal(conn_factory, gloom_sin_dex):
    resolver = _resolver(
        {GLOOM_CARD_ID: gloom_sin_dex},
        {"me02.5": [CardRef(id=GLOOM_CARD_ID, local_id="002", name="Erika's Gloom")]},
        [SET_ASCENDED],
        conn_factory,
    )
    reconocido = _reconocido(
        name="Erika's Gloom",
        set_name="Ascended Heroes",
        number="2/30",
        species=None,
        dex_number=None,
    )
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.necesita_revision is False
    assert resolucion.card is not None
    assert resolucion.card.dex_number is None


async def test_carta_con_dex_number_de_catalogo_no_valida_especie(conn_factory, charizard):
    """Charizard ya trae dex_number=6 de TCGdex: aunque el modelo mande una
    especie/dex contradictorios, no se toca -- la verdad del catálogo gana
    siempre, y no hace falta gastar una consulta a app.pokemon."""
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    reconocido = _reconocido(species="Bulbasaur", dex_number=1)
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.necesita_revision is False
    assert resolucion.card is not None
    assert resolucion.card.dex_number == 6
    assert resolucion.card.dex_number_inferido is False


async def test_sin_fila_en_app_pokemon_no_infiere_ni_marca(conn_factory, gloom_sin_dex):
    """`app.pokemon` sin sembrar todavía (antes del primer import del Excel)
    no es una contradicción del modelo: no hay con qué validar."""
    resolver = _resolver(
        {GLOOM_CARD_ID: gloom_sin_dex},
        {"me02.5": [CardRef(id=GLOOM_CARD_ID, local_id="002", name="Erika's Gloom")]},
        [SET_ASCENDED],
        conn_factory,
    )
    reconocido = _reconocido(
        name="Erika's Gloom",
        set_name="Ascended Heroes",
        number="2/30",
        species="Gloom",
        dex_number=44,
    )
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.necesita_revision is False
    assert resolucion.card is not None
    assert resolucion.card.dex_number is None
    assert resolucion.card.dex_number_inferido is False
