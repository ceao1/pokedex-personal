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
SET_JUNGLE = SetRef(id="jungle", name="Jungle", total=102)
SET_ASCENDED = SetRef(id="me02.5", name="Ascended Heroes", total=217, abbreviation="ASC")

GLOOM_CARD_ID = "me02.5-002"


class FakeCatalog:
    """Fake del CatalogPort: solo lo que `CardResolver` (a través de
    `CatalogService`) realmente llama."""

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

    async def get_set_detail(self, set_id: str):
        return next((s for s in self._sets if s.id == set_id), None)


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


def _card(card_id: str, name: str, set_id: str, set_name: str, local_id: str, dex: int | None):
    return parse_card(
        {
            "id": card_id,
            "name": name,
            "localId": local_id,
            "set": {"id": set_id, "name": set_name, "cardCount": {"official": 217}},
            "dexId": [dex] if dex is not None else None,
            "image": f"https://x/{card_id}",
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
        set_code=None,
        number="4/102",
        rarity="Rare Holo",
        species=None,
        dex_number=None,
        confidence=0.95,
        needs_review=False,
    )
    base.update(overrides)
    return Recognition(**base)


# --- Resolución básica por set + número -----------------------------------


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
    """Sin `set_code`, cae al denominador; sin un set que lo comparta,
    termina resolviendo por `set_name` (paso 3 de la cascada)."""
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SetRef(id="base1", name="Base Set", total=None)],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(set_name="base set", number="4"))
    assert resolucion.card is not None and resolucion.card.id == "base1-4"


async def test_set_inexistente_por_nombre_y_sin_denominador_que_resuelva(conn_factory):
    resolver = _resolver({}, {}, [SET_BASE], conn_factory)
    resolucion = await resolver.resolver(_reconocido(set_name="Set Que No Existe", number="4/999"))
    assert resolucion.card is None
    assert resolucion.necesita_revision is True


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


# --- needs_review / confidence ya no vetan --------------------------------
# (invierte lo que hacían las dos versiones anteriores de estos tests: la
# evidencia que motivó la task -- el Groudon real del dueño, confidence 0.5
# -- exige que esto resuelva cuando el catálogo confirma).


async def test_needs_review_del_modelo_no_veta_si_el_catalogo_confirma(conn_factory, charizard):
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(needs_review=True))
    assert resolucion.card is not None
    assert resolucion.card.id == "base1-4"
    assert resolucion.necesita_revision is False
    assert "dudó" in resolucion.motivo


async def test_confianza_baja_no_veta_si_el_catalogo_confirma(conn_factory, charizard):
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(confidence=0.5))
    assert resolucion.card is not None
    assert resolucion.card.id == "base1-4"
    assert resolucion.necesita_revision is False
    assert "dudó" in resolucion.motivo


async def test_sin_catalogo_que_confirme_needs_review_no_rescata_nada(conn_factory):
    """`needs_review` deja de ser veto, pero tampoco es una llave mágica: sin
    confirmación real del catálogo, sigue sin resolver."""
    resolver = _resolver({}, {}, [SET_BASE], conn_factory)
    resolucion = await resolver.resolver(
        _reconocido(needs_review=True, number="999/999", set_name=None)
    )
    assert resolucion.card is None
    assert resolucion.necesita_revision is True


# --- Los casos de la tabla del plan (task 2, paso 5) ----------------------


async def test_caso_real_drampa_resuelve_por_el_codigo_sin_mirar_el_denominador(conn_factory):
    """Caso real del dueño (Ascended Heroes, `176/217`). El denominador de
    otro set en el catálogo demuestra que, con código, no se lo mira."""
    drampa = _card("me02.5-176", "Drampa", "me02.5", "Ascended Heroes", "176", dex=780)
    resolver = _resolver(
        {"me02.5-176": drampa},
        {"me02.5": [CardRef(id="me02.5-176", local_id="176", name="Drampa")]},
        [SET_ASCENDED, SetRef(id="otro", name="Otro Set", total=217)],
        conn_factory,
    )
    reconocido = _reconocido(
        name="Drampa",
        set_name=None,
        set_code="ASC",
        number="176/217",
        species="Drampa",
        dex_number=780,
        confidence=0.8,
        needs_review=True,
    )
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.card is not None
    assert resolucion.card.id == "me02.5-176"
    assert resolucion.necesita_revision is False


async def test_caso_real_drampa_sin_codigo_resuelve_por_el_denominador(conn_factory):
    """Mismo caso real, pero el modelo no distinguió el código (`217` es
    único entre los sets de este catálogo de prueba)."""
    drampa = _card("me02.5-176", "Drampa", "me02.5", "Ascended Heroes", "176", dex=780)
    resolver = _resolver(
        {"me02.5-176": drampa},
        {"me02.5": [CardRef(id="me02.5-176", local_id="176", name="Drampa")]},
        [SET_ASCENDED],
        conn_factory,
    )
    reconocido = _reconocido(
        name="Drampa",
        set_name=None,
        set_code=None,
        number="176/217",
        species="Drampa",
        dex_number=780,
        confidence=0.8,
        needs_review=True,
    )
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.card is not None
    assert resolucion.card.id == "me02.5-176"
    assert resolucion.necesita_revision is False


async def test_caso_real_groudon_resuelve(conn_factory):
    groudon = _card("me02.5-108", "Groudon", "me02.5", "Ascended Heroes", "108", dex=383)
    resolver = _resolver(
        {"me02.5-108": groudon},
        {"me02.5": [CardRef(id="me02.5-108", local_id="108", name="Groudon")]},
        [SET_ASCENDED],
        conn_factory,
    )
    reconocido = _reconocido(
        name="Groudon",
        set_name=None,
        set_code=None,
        number="108/217",
        species="Groudon",
        dex_number=383,
        confidence=0.5,
        needs_review=True,
    )
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.card is not None
    assert resolucion.card.id == "me02.5-108"
    assert resolucion.necesita_revision is False


async def test_codigo_de_set_contradice_el_denominador(conn_factory):
    """Código apunta a un set y el denominador a otro: contradicción
    explícita, no se elige ninguno."""
    resolver = _resolver({}, {}, [SET_ASCENDED, SET_BASE], conn_factory)
    resolucion = await resolver.resolver(_reconocido(set_code="ASC", set_name=None, number="4/102"))
    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert "contradictorias" in resolucion.motivo


async def test_codigo_inexistente_en_el_catalogo_cae_al_denominador(conn_factory, charizard):
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(set_code="ZZZ", number="4/102"))
    assert resolucion.card is not None
    assert resolucion.card.id == "base1-4"


async def test_denominador_con_tres_sets_uno_solo_con_esa_carta_resuelve(conn_factory, charizard):
    otro_set_sin_esa_carta = SetRef(id="otro", name="Otro Set", total=102)
    resolver = _resolver(
        {"base1-4": charizard},
        {
            "base1": [CardRef(id="base1-4", local_id="4", name="Charizard")],
            "otro": [],
            "jungle": [],
        },
        [SET_BASE, SET_JUNGLE, otro_set_sin_esa_carta],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(set_name=None, number="4/102"))
    assert resolucion.card is not None
    assert resolucion.card.id == "base1-4"


async def test_denominador_con_tres_sets_dos_con_esa_carta_no_resuelve_solo(conn_factory):
    charizard_base = _card("base1-4", "Charizard", "base1", "Base Set", "4", dex=6)
    charizard_jungle = _card("jungle-4", "Charizard", "jungle", "Jungle", "4", dex=6)
    otro_sin_esa_carta = SetRef(id="otro", name="Otro Set", total=102)
    resolver = _resolver(
        {"base1-4": charizard_base, "jungle-4": charizard_jungle},
        {
            "base1": [CardRef(id="base1-4", local_id="4", name="Charizard")],
            "jungle": [CardRef(id="jungle-4", local_id="4", name="Charizard")],
            "otro": [],
        },
        [SET_BASE, SET_JUNGLE, otro_sin_esa_carta],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(set_name=None, number="4/102"))
    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert {c.id for c in resolucion.candidatas} == {"base1-4", "jungle-4"}


async def test_dex_id_contradice_la_especie_rechaza(conn_factory, charizard):
    """El ejemplo del brief: el `dexId` de la carta es 6 (Charizard real) y
    el modelo leyó dex 44 -- no se acepta aunque el nombre coincida."""
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(species="Gloom", dex_number=44))
    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert "contradictorias" in resolucion.motivo


async def test_sin_denominador_y_con_set_name_valido_resuelve_por_el_nombre(
    conn_factory, charizard
):
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SetRef(id="base1", name="Base Set", total=None)],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido(number="4", set_name="Base Set"))
    assert resolucion.card is not None
    assert resolucion.card.id == "base1-4"


async def test_sin_denominador_y_sin_set_name_no_resuelve(conn_factory):
    resolver = _resolver({}, {}, [SET_BASE], conn_factory)
    resolucion = await resolver.resolver(_reconocido(number="4", set_name=None))
    assert resolucion.card is None
    assert resolucion.necesita_revision is True


async def test_posesivo_de_entrenador_contra_especie_resuelve(conn_factory, gloom_sin_dex):
    resolver = _resolver(
        {GLOOM_CARD_ID: gloom_sin_dex},
        {"me02.5": [CardRef(id=GLOOM_CARD_ID, local_id="002", name="Erika's Gloom")]},
        [SET_ASCENDED],
        conn_factory,
    )
    reconocido = _reconocido(
        name="Erika's Gloom",
        set_name="Ascended Heroes",
        set_code=None,
        number="2/217",
        species="Gloom",
        dex_number=None,
    )
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.card is not None
    assert resolucion.card.id == GLOOM_CARD_ID
    assert resolucion.necesita_revision is False


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
        number="2/217",
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
        number="2/217",
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
        number="2/217",
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
        number="2/217",
        species=None,
        dex_number=None,
    )
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.necesita_revision is False
    assert resolucion.card is not None
    assert resolucion.card.dex_number is None


async def test_carta_con_dex_number_de_catalogo_no_valida_especie(conn_factory, charizard):
    """Charizard ya trae dex_number=6 de TCGdex: si el modelo no manda una
    especie/dex propios, no hay señal que contradiga y no hace falta
    gastar una consulta a app.pokemon."""
    resolver = _resolver(
        {"base1-4": charizard},
        {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
        [SET_BASE],
        conn_factory,
    )
    resolucion = await resolver.resolver(_reconocido())
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
        number="2/217",
        species="Gloom",
        dex_number=44,
    )
    resolucion = await resolver.resolver(reconocido)
    assert resolucion.necesita_revision is False
    assert resolucion.card is not None
    assert resolucion.card.dex_number is None
    assert resolucion.card.dex_number_inferido is False
