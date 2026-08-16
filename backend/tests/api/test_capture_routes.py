from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from pokedex.api.main import app
from pokedex.api.routes.capture import get_service
from pokedex.collection.service import CaptureService
from pokedex.collection.storage import FakeStorage

DRAFT = "aaaaaaaa-1111-1111-1111-111111111111"


@pytest.fixture()
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture()
def client(clean_db, fake_storage):
    """Cliente con el StoragePort sustituido por un fake, igual que
    `test_catalog_routes.py` sustituye el catálogo: la suite no puede pegarle
    a Supabase Storage real."""

    @contextmanager
    def conn_factory():
        yield clean_db

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
