from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from pokedex.api.main import app
from pokedex.api.routes.catalog import get_service
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import parse_card

from ..catalog.loaders import load_fixture

CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.fixture()
def client(clean_db):
    """Cliente con el servicio sustituido por un catálogo falso.

    Estos tests verifican ruteo y serialización, no la integración con
    TCGdex; esa la cubren el test de contrato y la prueba manual del
    Step 11. Sustituir la dependencia mantiene la suite offline, que es
    una restricción global de este plan.
    """
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)

    class FakeCatalog:
        async def get_card(self, card_id: str):
            return card if card_id == card.id else None

        async def find_by_set_and_number(self, set_id: str, local_id: str):
            return card if (set_id, local_id) == (card.set_id, card.local_id) else None

    @contextmanager
    def conn_factory():
        yield clean_db

    app.dependency_overrides[get_service] = lambda: CatalogService(FakeCatalog(), conn_factory)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_get_card_devuelve_la_ficha(client):
    response = client.get("/catalog/cards/sv03.5-001")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "sv03.5-001"
    assert body["name"] == "Bulbasaur"
    assert body["image_url"].endswith("/high.png")
    assert len(body["variants"]) >= 1


def test_get_card_inexistente_devuelve_404(client):
    response = client.get("/catalog/cards/set-que-no-existe-999")
    assert response.status_code == 404


def test_get_por_set_y_numero(client):
    response = client.get("/catalog/sets/sv03.5/001")
    assert response.status_code == 200
    assert response.json()["id"] == "sv03.5-001"


def test_la_ficha_no_expone_el_payload_crudo(client):
    """`raw` es detalle de implementación; no se sirve por HTTP."""
    body = client.get("/catalog/cards/sv03.5-001").json()
    assert "raw" not in body


def test_los_precios_llegan_por_variante(client):
    variantes = {v["id"]: v for v in client.get("/catalog/cards/sv03.5-001").json()["variants"]}
    assert variantes["endfynwn4n10gzq"]["price_usd"] == 0.25
    assert variantes["cm4kqul3x1bwlz1f"]["price_usd"] == 0.37
    assert variantes["3takscxpcqodqyjzqnsbuwq6"]["price_usd"] is None
