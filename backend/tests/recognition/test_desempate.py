"""Task 3: desempate por imagen cuando el catálogo confirma entre 2 y 5
cartas y ninguna señal (nombre, especie, dexId) alcanza para elegir una.

Los tests con `FakeCatalog`/`FakeRecognition` no pegan a la red. El único
que sí (`test_desempate_contract.py` -- marcado `contract`, excluido por
defecto) usa dos cartas reales del mismo Pokémon en sets distintos.
"""

from contextlib import contextmanager
from datetime import UTC, datetime

import httpx
import pytest
import respx

from pokedex.catalog.models import CardRef, SetRef
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import parse_card
from pokedex.recognition.gemini import FakeRecognition, GeminiRecognition
from pokedex.recognition.models import Recognition
from pokedex.recognition.ports import CandidataImagen
from pokedex.recognition.resolver import CardResolver

CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

SET_BASE = SetRef(id="base1", name="Base Set", total=102)
SET_JUNGLE = SetRef(id="jungle", name="Jungle", total=102)


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


def _card(card_id: str, set_id: str, set_name: str, local_id: str, image_url: str = "https://x/"):
    return parse_card(
        {
            "id": card_id,
            "name": "Charizard",
            "localId": local_id,
            "set": {"id": set_id, "name": set_name, "cardCount": {"official": 102}},
            "dexId": [6],
            "image": image_url + card_id,
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


@pytest.fixture()
async def http_client():
    async with httpx.AsyncClient() as c:
        yield c


def _reconocido(**overrides) -> Recognition:
    base = dict(
        name="Charizard",
        set_name=None,
        set_code=None,
        number="4/102",
        confidence=0.9,
        needs_review=False,
    )
    base.update(overrides)
    return Recognition(**base)


def _resolver_con_dos_candidatas(conn_factory, recognition, http_client) -> CardResolver:
    charizard_base = _card("base1-4", "base1", "Base Set", "4")
    charizard_jungle = _card("jungle-4", "jungle", "Jungle", "4")
    fake = FakeCatalog(
        {"base1-4": charizard_base, "jungle-4": charizard_jungle},
        {
            "base1": [CardRef(id="base1-4", local_id="4", name="Charizard")],
            "jungle": [CardRef(id="jungle-4", local_id="4", name="Charizard")],
        },
        [SET_BASE, SET_JUNGLE],
    )
    catalog = CatalogService(fake, conn_factory)
    return CardResolver(catalog, conn_factory, recognition=recognition, http_client=http_client)


@respx.mock
async def test_desempata_entre_dos_candidatas_con_la_foto(conn_factory, http_client):
    respx.get("https://x/base1-4/high.png").mock(
        return_value=httpx.Response(200, content=b"arte-base")
    )
    respx.get("https://x/jungle-4/high.png").mock(
        return_value=httpx.Response(200, content=b"arte-jungle")
    )
    recognition = FakeRecognition(elegir_resultado="jungle-4")
    resolver = _resolver_con_dos_candidatas(conn_factory, recognition, http_client)

    resolucion = await resolver.resolver(_reconocido(), foto=b"foto-del-dueno")

    assert resolucion.card is not None
    assert resolucion.card.id == "jungle-4"
    assert resolucion.necesita_revision is False
    assert "desempató" in resolucion.motivo
    # Se le pasó la foto del dueño y las dos candidatas con su arte.
    assert len(recognition.elegir_calls) == 1
    foto_enviada, candidatas_enviadas = recognition.elegir_calls[0]
    assert foto_enviada == b"foto-del-dueno"
    assert {c.card_id for c in candidatas_enviadas} == {"base1-4", "jungle-4"}


@respx.mock
async def test_sin_desempate_claro_cae_a_revision_manual(conn_factory, http_client):
    respx.get("https://x/base1-4/high.png").mock(
        return_value=httpx.Response(200, content=b"arte-base")
    )
    respx.get("https://x/jungle-4/high.png").mock(
        return_value=httpx.Response(200, content=b"arte-jungle")
    )
    recognition = FakeRecognition(elegir_resultado=None)
    resolver = _resolver_con_dos_candidatas(conn_factory, recognition, http_client)

    resolucion = await resolver.resolver(_reconocido(), foto=b"foto-del-dueno")

    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert {c.id for c in resolucion.candidatas} == {"base1-4", "jungle-4"}


async def test_sin_foto_no_intenta_el_desempate(conn_factory, http_client):
    recognition = FakeRecognition(elegir_resultado="jungle-4")
    resolver = _resolver_con_dos_candidatas(conn_factory, recognition, http_client)

    resolucion = await resolver.resolver(_reconocido(), foto=None)

    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert recognition.elegir_calls == [], "sin foto no hay nada que comparar"


async def test_sin_recognition_port_no_intenta_el_desempate(conn_factory, http_client):
    charizard_base = _card("base1-4", "base1", "Base Set", "4")
    charizard_jungle = _card("jungle-4", "jungle", "Jungle", "4")
    fake = FakeCatalog(
        {"base1-4": charizard_base, "jungle-4": charizard_jungle},
        {
            "base1": [CardRef(id="base1-4", local_id="4", name="Charizard")],
            "jungle": [CardRef(id="jungle-4", local_id="4", name="Charizard")],
        },
        [SET_BASE, SET_JUNGLE],
    )
    # Constructor sin `recognition` ni `http_client` -- el comportamiento por
    # defecto de la mayoría de los tests de `test_resolver.py`.
    resolver = CardResolver(CatalogService(fake, conn_factory), conn_factory)

    resolucion = await resolver.resolver(_reconocido(), foto=b"foto-del-dueno")

    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert len(resolucion.candidatas) == 2


async def test_mas_de_cinco_candidatas_no_desempata(conn_factory, http_client):
    sets = []
    set_cards = {}
    cards = {}
    for i in range(6):
        set_id = f"set{i}"
        card_id = f"{set_id}-4"
        sets.append(SetRef(id=set_id, name=f"Set {i}", total=102))
        set_cards[set_id] = [CardRef(id=card_id, local_id="4", name="Charizard")]
        cards[card_id] = _card(card_id, set_id, f"Set {i}", "4")

    fake = FakeCatalog(cards, set_cards, sets)
    recognition = FakeRecognition(elegir_resultado="set0-4")
    resolver = CardResolver(
        CatalogService(fake, conn_factory),
        conn_factory,
        recognition=recognition,
        http_client=http_client,
    )

    resolucion = await resolver.resolver(_reconocido(), foto=b"foto-del-dueno")

    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert len(resolucion.candidatas) == 6
    assert recognition.elegir_calls == [], "más de cinco candidatas no manda fotos de más"


@respx.mock
async def test_un_card_id_que_no_estaba_entre_las_candidatas_se_descarta(conn_factory, http_client):
    """Alucinación del modelo: devuelve un id que no le pasamos. Se
    descarta -- no se acepta a ciegas -- y cae a revisión manual."""
    respx.get("https://x/base1-4/high.png").mock(
        return_value=httpx.Response(200, content=b"arte-base")
    )
    respx.get("https://x/jungle-4/high.png").mock(
        return_value=httpx.Response(200, content=b"arte-jungle")
    )
    recognition = FakeRecognition(elegir_resultado="un-id-inventado")
    resolver = _resolver_con_dos_candidatas(conn_factory, recognition, http_client)

    resolucion = await resolver.resolver(_reconocido(), foto=b"foto-del-dueno")

    assert resolucion.card is None
    assert resolucion.necesita_revision is True


async def test_candidata_sin_image_url_no_desempata(conn_factory, http_client):
    charizard_base = _card("base1-4", "base1", "Base Set", "4")
    charizard_base.image_url = None
    charizard_jungle = _card("jungle-4", "jungle", "Jungle", "4")
    fake = FakeCatalog(
        {"base1-4": charizard_base, "jungle-4": charizard_jungle},
        {
            "base1": [CardRef(id="base1-4", local_id="4", name="Charizard")],
            "jungle": [CardRef(id="jungle-4", local_id="4", name="Charizard")],
        },
        [SET_BASE, SET_JUNGLE],
    )
    recognition = FakeRecognition(elegir_resultado="jungle-4")
    resolver = CardResolver(
        CatalogService(fake, conn_factory),
        conn_factory,
        recognition=recognition,
        http_client=http_client,
    )

    resolucion = await resolver.resolver(_reconocido(), foto=b"foto-del-dueno")

    assert resolucion.card is None
    assert resolucion.necesita_revision is True
    assert recognition.elegir_calls == []


# --- GeminiRecognition.elegir_entre: forma de la petición y parseo --------

MODEL = "gemini-3.5-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def _gemini_response(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}


@respx.mock
async def test_elegir_entre_parsea_el_card_id_elegido():
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=_gemini_response('{"card_id":"jungle-4"}'))
    )
    async with httpx.AsyncClient() as client:
        elegido = await GeminiRecognition("clave", MODEL, client).elegir_entre(
            b"foto",
            [
                CandidataImagen(card_id="base1-4", image=b"arte-base"),
                CandidataImagen(card_id="jungle-4", image=b"arte-jungle"),
            ],
        )
    assert elegido == "jungle-4"


@respx.mock
async def test_elegir_entre_null_se_parsea_como_none():
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=_gemini_response('{"card_id":null}'))
    )
    async with httpx.AsyncClient() as client:
        elegido = await GeminiRecognition("clave", MODEL, client).elegir_entre(
            b"foto", [CandidataImagen(card_id="base1-4", image=b"arte-base")]
        )
    assert elegido is None


@respx.mock
async def test_elegir_entre_manda_la_foto_y_cada_candidata_numerada():
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json=_gemini_response('{"card_id":"base1-4"}'))
    )
    async with httpx.AsyncClient() as client:
        await GeminiRecognition("clave", MODEL, client).elegir_entre(
            b"foto-dueno",
            [
                CandidataImagen(card_id="base1-4", image=b"arte-base"),
                CandidataImagen(card_id="jungle-4", image=b"arte-jungle"),
            ],
        )
    payload = route.calls[0].request.content
    import json

    body = json.loads(payload)
    parts = body["contents"][0]["parts"]
    # La foto del dueño primero (texto del prompt + su imagen), luego cada
    # candidata numerada (un texto "Candidata: <id>" seguido de su imagen).
    textos_candidata = [
        p["text"] for p in parts if "text" in p and p["text"].startswith("Candidata")
    ]
    assert textos_candidata == ["Candidata: base1-4", "Candidata: jungle-4"]
