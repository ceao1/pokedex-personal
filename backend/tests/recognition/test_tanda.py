"""Task 3: identificar varias cartas en una foto.

`GeminiRecognition.identificar_varias` (parseo del array que devuelve el
modelo, incluido el sufijo de idioma pegado al código de set) se prueba acá
con `respx`, sin red real. `CardResolver.resolver_varias` (reutiliza
`resolver()` entero por cada lectura) se prueba con `FakeCatalog`/
`FakeRecognition`, igual que `test_desempate.py`.

El único test que pega a Gemini de verdad vive en `test_tanda_contract.py`
(marca `contract`, excluido por defecto).
"""

from contextlib import contextmanager
from datetime import UTC, datetime

import httpx
import pytest
import respx

from pokedex.catalog.models import CardRef, SetRef
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import parse_card
from pokedex.recognition.gemini import FakeRecognition, GeminiRecognition, _strip_language_suffix
from pokedex.recognition.models import Recognition
from pokedex.recognition.resolver import MAX_TANDA, CardResolver

MODEL = "gemini-3.5-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def _gemini_response(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}


# --- GeminiRecognition.identificar_varias: forma de la petición y parseo ---


@respx.mock
async def test_identificar_varias_parsea_un_array_en_orden():
    texto = (
        '[{"name":"Charmander","number":"20/217","confidence":0.9,"needs_review":false},'
        '{"name":"Psyduck","number":"39/217","confidence":0.95,"needs_review":false}]'
    )
    respx.post(URL).mock(return_value=httpx.Response(200, json=_gemini_response(texto)))
    async with httpx.AsyncClient() as client:
        lecturas = await GeminiRecognition("clave", MODEL, client).identificar_varias(
            b"foto-compuesta", "image/jpeg"
        )

    assert len(lecturas) == 2
    assert lecturas[0].name == "Charmander"
    assert lecturas[0].number == "20/217"
    assert lecturas[1].name == "Psyduck"
    assert lecturas[1].number == "39/217"


@respx.mock
async def test_identificar_varias_separa_el_sufijo_de_idioma_del_set_code():
    """Medido a mano (ver el plan): Gemini devuelve `ASCen` -- el código
    `ASC` pegado al sufijo de idioma `en` de TCGdex -- en vez de solo el
    código. El parser lo separa antes de que llegue al `CardResolver`."""
    texto = '[{"name":"Charmander","set_code":"ASCen","number":"20/217"}]'
    respx.post(URL).mock(return_value=httpx.Response(200, json=_gemini_response(texto)))
    async with httpx.AsyncClient() as client:
        lecturas = await GeminiRecognition("clave", MODEL, client).identificar_varias(
            b"foto", "image/jpeg"
        )

    assert lecturas[0].set_code == "ASC"


@respx.mock
async def test_identificar_varias_con_json_no_es_lista_devuelve_vacio():
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=_gemini_response('{"name":"no es un array"}'))
    )
    async with httpx.AsyncClient() as client:
        lecturas = await GeminiRecognition("clave", MODEL, client).identificar_varias(
            b"foto", "image/jpeg"
        )
    assert lecturas == []


@respx.mock
async def test_identificar_varias_con_texto_no_json_devuelve_vacio():
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=_gemini_response("no puedo leer nada"))
    )
    async with httpx.AsyncClient() as client:
        lecturas = await GeminiRecognition("clave", MODEL, client).identificar_varias(
            b"foto", "image/jpeg"
        )
    assert lecturas == []


@respx.mock
async def test_identificar_varias_ignora_elementos_que_no_son_objetos():
    texto = '[{"name":"Charmander","number":"20/217"}, "basura", null]'
    respx.post(URL).mock(return_value=httpx.Response(200, json=_gemini_response(texto)))
    async with httpx.AsyncClient() as client:
        lecturas = await GeminiRecognition("clave", MODEL, client).identificar_varias(
            b"foto", "image/jpeg"
        )
    assert len(lecturas) == 1
    assert lecturas[0].name == "Charmander"


# --- _strip_language_suffix: la regla en aislamiento ------------------------


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("ASCen", "ASC"),
        ("ASC", "ASC"),
        ("BS", "BS"),
        (None, None),
        ("", ""),
        ("ASCes", "ASC"),
        # Un código real de solo dos letras (sin dígitos) tampoco se toca si
        # no tiene sufijo en minúsculas pegado.
        ("JU", "JU"),
    ],
)
def test_strip_language_suffix(crudo, esperado):
    assert _strip_language_suffix(crudo) == esperado


# --- CardResolver.resolver_varias: reutiliza resolver() entero -------------


class FakeCatalog:
    def __init__(self, cards: dict, set_cards: dict, sets: list[SetRef]):
        self._cards = cards
        self._set_cards = set_cards
        self._sets = sets

    async def get_card(self, card_id: str):
        return self._cards.get(card_id)

    async def find_by_set_and_number(self, set_id: str, local_id: str):
        raise NotImplementedError

    async def list_set_cards(self, set_id: str):
        return self._set_cards.get(set_id, [])

    async def list_sets(self):
        return self._sets

    async def get_set_detail(self, set_id: str):
        return next((s for s in self._sets if s.id == set_id), None)


SET_ASCENDED = SetRef(id="me02.5", name="Ascended Heroes", total=217, abbreviation="ASC")
CAPTURED_AT = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _carta(card_id: str, local_id: str, name: str, dex_number: int | None = None):
    return parse_card(
        {
            "id": card_id,
            "name": name,
            "localId": local_id,
            "set": {"id": "me02.5", "name": "Ascended Heroes", "cardCount": {"official": 217}},
            "dexId": [dex_number] if dex_number else [],
            "image": f"https://x/{card_id}",
            "variants_detailed": [],
        },
        CAPTURED_AT,
    )


@pytest.fixture()
def conn_factory(clean_db):
    @contextmanager
    def factory():
        yield clean_db

    return factory


def _resolver(conn_factory, recognition) -> CardResolver:
    charmander = _carta("me02.5-020", "020", "Charmander", 4)
    psyduck = _carta("me02.5-039", "039", "Psyduck", 54)
    fake = FakeCatalog(
        {"me02.5-020": charmander, "me02.5-039": psyduck},
        {
            "me02.5": [
                CardRef(id="me02.5-020", local_id="020", name="Charmander"),
                CardRef(id="me02.5-039", local_id="039", name="Psyduck"),
            ]
        },
        [SET_ASCENDED],
    )
    catalog = CatalogService(fake, conn_factory)
    return CardResolver(catalog, conn_factory, recognition=recognition)


async def test_resolver_varias_resuelve_cada_lectura_por_separado(conn_factory):
    recognition = FakeRecognition(
        resultado_varias=[
            Recognition(name="Charmander", number="20/217", confidence=0.9, needs_review=False),
            Recognition(name="Psyduck", number="39/217", confidence=0.9, needs_review=False),
        ]
    )
    resolver = _resolver(conn_factory, recognition)

    tanda = await resolver.resolver_varias(b"foto-compuesta", "image/jpeg")

    assert tanda.total_encontradas == 2
    assert tanda.excede_limite is False
    assert [r.card.id for r in tanda.resoluciones] == ["me02.5-020", "me02.5-039"]
    assert all(r.necesita_revision is False for r in tanda.resoluciones)
    # La foto que se le pasó a identificar_varias es la compuesta completa.
    assert recognition.varias_calls == [(b"foto-compuesta", "image/jpeg")]


async def test_resolver_varias_no_inventa_ni_saltea_una_lectura_dudosa(conn_factory):
    """Una lectura sin número (el modelo no la pudo leer con certeza) no
    desaparece: entra igual, resuelta como revisión manual -- ninguna carta
    se inventa ni se descarta en silencio."""
    recognition = FakeRecognition(
        resultado_varias=[
            Recognition(name="Charmander", number="20/217", confidence=0.9, needs_review=False),
            Recognition(name=None, number=None, confidence=0.0, needs_review=True),
        ]
    )
    resolver = _resolver(conn_factory, recognition)

    tanda = await resolver.resolver_varias(b"foto", "image/jpeg")

    assert tanda.total_encontradas == 2
    assert tanda.resoluciones[0].card is not None
    assert tanda.resoluciones[1].card is None
    assert tanda.resoluciones[1].necesita_revision is True


async def test_resolver_varias_marca_cuando_excede_el_limite(conn_factory):
    lecturas = [
        Recognition(name="Charmander", number="20/217", confidence=0.9, needs_review=False)
        for _ in range(MAX_TANDA + 1)
    ]
    recognition = FakeRecognition(resultado_varias=lecturas)
    resolver = _resolver(conn_factory, recognition)

    tanda = await resolver.resolver_varias(b"foto", "image/jpeg")

    assert tanda.total_encontradas == MAX_TANDA + 1
    assert tanda.excede_limite is True
    # Se aceptan igual -- no se recortan a las primeras doce.
    assert len(tanda.resoluciones) == MAX_TANDA + 1


async def test_resolver_varias_con_doce_no_excede_el_limite(conn_factory):
    lecturas = [
        Recognition(name="Charmander", number="20/217", confidence=0.9, needs_review=False)
        for _ in range(MAX_TANDA)
    ]
    recognition = FakeRecognition(resultado_varias=lecturas)
    resolver = _resolver(conn_factory, recognition)

    tanda = await resolver.resolver_varias(b"foto", "image/jpeg")

    assert tanda.total_encontradas == MAX_TANDA
    assert tanda.excede_limite is False
