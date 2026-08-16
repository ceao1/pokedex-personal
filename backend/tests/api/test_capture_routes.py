from contextlib import contextmanager
from datetime import UTC, datetime

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from pokedex.api.main import app
from pokedex.api.routes.capture import get_identification_service, get_service
from pokedex.catalog.models import CardRef, SetRef
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import parse_card
from pokedex.collection.service import CaptureService, IdentificationService
from pokedex.collection.storage import FakeStorage
from pokedex.config import settings
from pokedex.recognition.gemini import FakeRecognition
from pokedex.recognition.models import Recognition
from pokedex.recognition.resolver import CardResolver

from ..catalog.loaders import load_fixture

DRAFT = "aaaaaaaa-1111-1111-1111-111111111111"
CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.fixture()
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture()
def conn_factory(clean_db):
    @contextmanager
    def factory():
        yield clean_db

    return factory


@pytest.fixture()
def client(clean_db, fake_storage, conn_factory):
    """Cliente con el StoragePort sustituido por un fake, igual que
    `test_catalog_routes.py` sustituye el catálogo: la suite no puede pegarle
    a Supabase Storage real."""
    app.dependency_overrides[get_service] = lambda: CaptureService(fake_storage, conn_factory)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_post_captures_devuelve_las_dos_urls_firmadas(client, fake_storage):
    response = client.post("/captures", json={"client_draft_id": DRAFT})
    assert response.status_code == 200
    body = response.json()
    assert body["client_draft_id"] == DRAFT
    assert body["uploads"]["front"]
    assert body["uploads"]["thumb"]
    # Las rutas se derivan del client_draft_id, no al azar: es lo que hace
    # que un reintento (mientras el archivo no haya llegado) pida de nuevo la
    # firma para el mismo par de rutas en vez de dejar huérfano el primero.
    assert fake_storage.signed_uploads == [f"{DRAFT}/front.jpg", f"{DRAFT}/thumb.jpg"]


def test_post_captures_es_idempotente(client, clean_db):
    client.post("/captures", json={"client_draft_id": DRAFT})
    client.post("/captures", json={"client_draft_id": DRAFT})
    total = clean_db.execute("select count(*) as n from app.owned_copy").fetchone()["n"]
    assert total == 1


def test_post_captures_reintento_con_foto_ya_subida_no_revienta(client, clean_db, fake_storage):
    """Reproduce el caso que motiva `client_draft_id`: el celular subió la
    foto directo al bucket, la respuesta de este POST se perdió en el
    camino, y el celular reintenta. Verificado a mano contra Supabase
    Storage real: re-firmar la subida de un path que ya tiene objeto
    devuelve 409 -- si eso se propagara tal cual, el reintento vería un 500
    en vez de la idempotencia que `client_draft_id` promete."""
    client.post("/captures", json={"client_draft_id": DRAFT})
    fake_storage.already_uploaded.add(f"{DRAFT}/front.jpg")
    fake_storage.already_uploaded.add(f"{DRAFT}/thumb.jpg")

    response = client.post("/captures", json={"client_draft_id": DRAFT})
    assert response.status_code == 200

    total = clean_db.execute("select count(*) as n from app.owned_copy").fetchone()["n"]
    assert total == 1


def test_photo_uploaded_marca_las_fotos(client):
    client.post("/captures", json={"client_draft_id": DRAFT})
    response = client.post(f"/captures/{DRAFT}/photo-uploaded")
    assert response.status_code == 200
    body = response.json()
    # No solo truthy: el bucket es privado (decisión de diseño), así que lo
    # que llega por HTTP tiene que ser la URL de *descarga* firmada que el
    # backend mintió, no el path crudo que guarda el repositorio.
    assert "fake.storage.test/download" in body["photo_front_url"]
    assert "fake.storage.test/download" in body["photo_thumb_url"]


def test_photo_uploaded_sobre_borrador_inexistente_da_404(client):
    otro = "bbbbbbbb-1111-1111-1111-111111111111"
    response = client.post(f"/captures/{otro}/photo-uploaded")
    assert response.status_code == 404


def test_patch_actualiza_campos_parcialmente(client):
    client.post("/captures", json={"client_draft_id": DRAFT})
    client.patch(f"/captures/{DRAFT}", json={"condition": "NM", "notes": "ejemplo"})
    response = client.patch(f"/captures/{DRAFT}", json={"condition": "LP"})
    assert response.status_code == 200
    body = response.json()
    assert body["condition"] == "LP"
    assert body["notes"] == "ejemplo"


def test_patch_vacio_no_revienta(client):
    client.post("/captures", json={"client_draft_id": DRAFT})
    response = client.patch(f"/captures/{DRAFT}", json={})
    assert response.status_code == 200


def test_patch_sobre_borrador_inexistente_da_404(client):
    otro = "cccccccc-1111-1111-1111-111111111111"
    response = client.patch(f"/captures/{otro}", json={"condition": "NM"})
    assert response.status_code == 404


def test_patch_con_precio_devuelve_float(client):
    client.post("/captures", json={"client_draft_id": DRAFT})
    response = client.patch(f"/captures/{DRAFT}", json={"purchase_price_usd": "12.50"})
    assert response.status_code == 200
    assert response.json()["purchase_price_usd"] == 12.5


def test_get_pendientes_excluye_los_listos(client):
    otro = "dddddddd-1111-1111-1111-111111111111"
    client.post("/captures", json={"client_draft_id": DRAFT})
    client.post("/captures", json={"client_draft_id": otro})
    client.patch(f"/captures/{otro}", json={"capture_status": "listo"})

    response = client.get("/captures/pendientes")
    assert response.status_code == 200
    ids = {c["client_draft_id"] for c in response.json()}
    assert DRAFT in ids
    assert otro not in ids


# --- POST /captures/{id}/identificar --------------------------------------


class FakeCatalog:
    """Fake del CatalogPort, mínimo para lo que `CardResolver` necesita."""

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


DOWNLOAD_URL = f"https://fake.storage.test/download/{DRAFT}/front.jpg?expires=600"


def _identification_service(
    recognition: Recognition, conn_factory, http_client
) -> IdentificationService:
    charizard = parse_card(load_fixture("card_base1-4"), CAPTURED_AT)
    catalog = CatalogService(
        FakeCatalog(
            {"base1-4": charizard},
            {"base1": [CardRef(id="base1-4", local_id="4", name="Charizard")]},
            [SetRef(id="base1", name="Base Set", total=102)],
        ),
        conn_factory,
    )
    resolver = CardResolver(catalog, conn_factory)
    return IdentificationService(
        FakeStorage(), FakeRecognition(result=recognition), resolver, conn_factory, http_client
    )


@pytest.fixture()
async def http_client():
    async with httpx.AsyncClient() as c:
        yield c


@respx.mock
async def test_identificar_con_confianza_alta_devuelve_la_carta(client, conn_factory, http_client):
    client.post("/captures", json={"client_draft_id": DRAFT})
    client.post(f"/captures/{DRAFT}/photo-uploaded")
    respx.get(DOWNLOAD_URL).mock(
        return_value=httpx.Response(200, content=b"foto", headers={"content-type": "image/jpeg"})
    )
    reconocido = Recognition(
        name="Charizard",
        set_name="Base Set",
        number="4/102",
        rarity="Rare Holo",
        confidence=0.95,
        needs_review=False,
    )
    app.dependency_overrides[get_identification_service] = lambda: _identification_service(
        reconocido, conn_factory, http_client
    )

    response = client.post(f"/captures/{DRAFT}/identificar")

    assert response.status_code == 200
    body = response.json()
    assert body["carta"]["id"] == "base1-4"
    assert body["necesita_revision"] is False
    assert body["reconocido"]["name"] == "Charizard"
    assert "raw" not in body["reconocido"]


@respx.mock
async def test_identificar_con_confianza_baja_pero_catalogo_confirma_devuelve_la_carta(
    client, conn_factory, http_client
):
    """La confianza del modelo ya no veta (task "identificar por lo impreso
    en la carta"): lo que decide es si el catálogo confirma. Reproduce el
    caso real del dueño (Groudon, confidence 0.5) a escala de la ruta HTTP."""
    client.post("/captures", json={"client_draft_id": DRAFT})
    client.post(f"/captures/{DRAFT}/photo-uploaded")
    respx.get(DOWNLOAD_URL).mock(
        return_value=httpx.Response(200, content=b"foto", headers={"content-type": "image/jpeg"})
    )
    reconocido = Recognition(
        name="Charizard",
        set_name="Base Set",
        number="4/102",
        confidence=0.3,
        needs_review=False,
    )
    app.dependency_overrides[get_identification_service] = lambda: _identification_service(
        reconocido, conn_factory, http_client
    )

    response = client.post(f"/captures/{DRAFT}/identificar")

    assert response.status_code == 200
    body = response.json()
    assert body["carta"]["id"] == "base1-4"
    assert body["necesita_revision"] is False


@respx.mock
async def test_identificar_sin_confirmacion_del_catalogo_no_devuelve_carta(
    client, conn_factory, http_client
):
    """La contraparte: sin nada que el catálogo pueda confirmar (número
    inexistente en el set), la duda del modelo ya no importa -- pero
    tampoco resuelve porque no hay ninguna carta real detrás."""
    client.post("/captures", json={"client_draft_id": DRAFT})
    client.post(f"/captures/{DRAFT}/photo-uploaded")
    respx.get(DOWNLOAD_URL).mock(
        return_value=httpx.Response(200, content=b"foto", headers={"content-type": "image/jpeg"})
    )
    reconocido = Recognition(
        name="Charizard",
        set_name="Base Set",
        number="999/102",
        confidence=0.3,
        needs_review=False,
    )
    app.dependency_overrides[get_identification_service] = lambda: _identification_service(
        reconocido, conn_factory, http_client
    )

    response = client.post(f"/captures/{DRAFT}/identificar")

    assert response.status_code == 200
    body = response.json()
    assert body["carta"] is None
    assert body["necesita_revision"] is True


def test_identificar_sin_llave_configurada_devuelve_503(client, monkeypatch):
    """Sin overridear `get_identification_service`: corre la dependencia
    real, que mira `settings.gemini_api` antes de tocar Storage o la red."""
    monkeypatch.setattr(settings, "gemini_api", "")
    client.post("/captures", json={"client_draft_id": DRAFT})

    response = client.post(f"/captures/{DRAFT}/identificar")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "apagada" in detail
    assert "a mano" in detail


@respx.mock
async def test_identificar_no_escribe_nada_en_owned_copy(
    client, conn_factory, clean_db, http_client
):
    client.post("/captures", json={"client_draft_id": DRAFT})
    client.post(f"/captures/{DRAFT}/photo-uploaded")
    respx.get(DOWNLOAD_URL).mock(
        return_value=httpx.Response(200, content=b"foto", headers={"content-type": "image/jpeg"})
    )
    antes = clean_db.execute(
        "select * from app.owned_copy where client_draft_id = %(d)s", {"d": DRAFT}
    ).fetchone()

    reconocido = Recognition(
        name="Charizard", set_name="Base Set", number="4/102", confidence=0.95, needs_review=False
    )
    app.dependency_overrides[get_identification_service] = lambda: _identification_service(
        reconocido, conn_factory, http_client
    )
    response = client.post(f"/captures/{DRAFT}/identificar")
    assert response.status_code == 200

    despues = clean_db.execute(
        "select * from app.owned_copy where client_draft_id = %(d)s", {"d": DRAFT}
    ).fetchone()
    assert antes == despues


def test_identificar_sobre_borrador_inexistente_da_404(client):
    otro = "eeeeeeee-1111-1111-1111-111111111111"
    response = client.post(f"/captures/{otro}/identificar")
    assert response.status_code == 404


@respx.mock
async def test_identificar_sin_foto_subida_da_409(client, conn_factory, http_client):
    client.post("/captures", json={"client_draft_id": DRAFT})
    reconocido = Recognition(confidence=0.0)
    app.dependency_overrides[get_identification_service] = lambda: _identification_service(
        reconocido, conn_factory, http_client
    )

    response = client.post(f"/captures/{DRAFT}/identificar")

    assert response.status_code == 409
