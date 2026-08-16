"""Task 4: el endpoint de la compra, de punta a punta contra un
`RecognitionPort` falso y un `CatalogPort` falso -- sin red real."""

from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from pokedex.api.main import app
from pokedex.api.routes.purchases import get_service
from pokedex.catalog.models import CardRef, CardVariant, SetRef
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import parse_card
from pokedex.collection.storage import FakeStorage
from pokedex.config import settings
from pokedex.purchases.service import PurchaseService
from pokedex.recognition.gemini import FakeRecognition
from pokedex.recognition.models import Recognition
from pokedex.recognition.resolver import CardResolver

CAPTURED_AT = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


class FakeCatalog:
    """Mínimo para lo que `CardResolver`/`PurchaseService` necesitan --
    mismo patrón que `test_capture_routes.py`."""

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


def _carta(card_id: str, local_id: str, name: str, dex_number: int, precio: str | None = None):
    card = parse_card(
        {
            "id": card_id,
            "name": name,
            "localId": local_id,
            "set": {"id": "me02.5", "name": "Ascended Heroes", "cardCount": {"official": 217}},
            "dexId": [dex_number],
            "image": f"https://x/{card_id}",
            "variants_detailed": [],
        },
        CAPTURED_AT,
    )
    variante = CardVariant(
        id="normal",
        type="normal",
        price_usd=Decimal(precio) if precio is not None else None,
        price_captured_at=CAPTURED_AT if precio is not None else None,
        raw={},
    )
    card.variants = [variante]
    return card


SET_ASCENDED = SetRef(id="me02.5", name="Ascended Heroes", total=217, abbreviation="ASC")

CHARMANDER = _carta("me02.5-020", "020", "Charmander", 4, "5.00")
PSYDUCK = _carta("me02.5-039", "039", "Psyduck", 54, "15.00")
MEGANIUM = _carta("me02.5-010", "010", "Mega Meganium ex", 154, None)


@pytest.fixture()
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture()
def conn_factory(clean_db):
    @contextmanager
    def factory():
        yield clean_db

    return factory


def _catalog_con_conn(conn_factory) -> CatalogService:
    fake = FakeCatalog(
        {"me02.5-020": CHARMANDER, "me02.5-039": PSYDUCK, "me02.5-010": MEGANIUM},
        {
            "me02.5": [
                CardRef(id="me02.5-020", local_id="020", name="Charmander"),
                CardRef(id="me02.5-039", local_id="039", name="Psyduck"),
                CardRef(id="me02.5-010", local_id="010", name="Mega Meganium ex"),
            ]
        },
        [SET_ASCENDED],
    )
    return CatalogService(fake, conn_factory)


def _service(conn_factory, fake_storage, resultado_varias=None) -> PurchaseService:
    catalog = _catalog_con_conn(conn_factory)
    resolver = None
    if resultado_varias is not None:
        recognition = FakeRecognition(resultado_varias=resultado_varias)
        resolver = CardResolver(catalog, conn_factory, recognition=recognition)
    return PurchaseService(fake_storage, catalog, resolver, conn_factory)


@pytest.fixture()
def client(conn_factory, fake_storage):
    app.dependency_overrides[get_service] = lambda: _service(conn_factory, fake_storage)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _crear_compra(client, total="40.00", source_type="lote") -> int:
    response = client.post("/compras", json={"source_type": source_type, "total_usd": total})
    assert response.status_code == 200
    return response.json()["id"]


# --- POST /compras -----------------------------------------------------------


def test_crear_compra_devuelve_su_id_y_metodo_por_defecto(client):
    response = client.post("/compras", json={"source_type": "sobre", "total_usd": "12.50"})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] > 0
    assert body["source_type"] == "sobre"
    assert body["total_usd"] == 12.50
    assert body["allocation_method"] == "market_value"


def test_get_compra_inexistente_da_404(client):
    response = client.get("/compras/999999")
    assert response.status_code == 404


# --- POST /compras/{id}/tanda: propone, no guarda nada ----------------------


def test_tanda_de_tres_propone_tres_y_no_guarda_nada(clean_db, fake_storage, conn_factory):
    resultado_varias = [
        Recognition(name="Charmander", number="20/217", confidence=0.9, needs_review=False),
        Recognition(name="Psyduck", number="39/217", confidence=0.9, needs_review=False),
        Recognition(name=None, number=None, confidence=0.0, needs_review=True),
    ]
    app.dependency_overrides[get_service] = lambda: _service(
        conn_factory, fake_storage, resultado_varias=resultado_varias
    )
    with TestClient(app) as client:
        purchase_id = _crear_compra(client)

        response = client.post(
            f"/compras/{purchase_id}/tanda",
            content=b"foto-compuesta",
            headers={"content-type": "image/jpeg"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total_encontradas"] == 3
        assert body["excede_limite"] is False
        assert len(body["lecturas"]) == 3
        assert body["lecturas"][0]["carta"]["id"] == "me02.5-020"
        assert body["lecturas"][1]["carta"]["id"] == "me02.5-039"
        assert body["lecturas"][2]["carta"] is None
        assert body["lecturas"][2]["necesita_revision"] is True

        total = clean_db.execute("select count(*) as n from app.owned_copy").fetchone()["n"]
        assert total == 0, "una tanda propone, nunca guarda"
    app.dependency_overrides.clear()


def test_tanda_guarda_la_foto_en_la_compra_no_en_cada_ejemplar(
    clean_db, fake_storage, conn_factory
):
    resultado_varias = [
        Recognition(name="Charmander", number="20/217", confidence=0.9, needs_review=False)
    ]
    app.dependency_overrides[get_service] = lambda: _service(
        conn_factory, fake_storage, resultado_varias=resultado_varias
    )
    with TestClient(app) as client:
        purchase_id = _crear_compra(client)
        client.post(
            f"/compras/{purchase_id}/tanda",
            content=b"foto-compuesta",
            headers={"content-type": "image/jpeg"},
        )
        compra = client.get(f"/compras/{purchase_id}").json()
        assert compra["photo_url"] is not None
        assert len(fake_storage.uploads) == 1
        path, data, content_type = fake_storage.uploads[0]
        assert path.startswith(f"purchases/{purchase_id}/tanda-")
        assert data == b"foto-compuesta"
        assert content_type == "image/jpeg"
    app.dependency_overrides.clear()


def test_tanda_sin_gemini_configurado_da_503(client, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api", "")
    app.dependency_overrides.clear()  # usa la dependencia real
    with TestClient(app) as real_client:
        purchase_id = _crear_compra(real_client)
        response = real_client.post(
            f"/compras/{purchase_id}/tanda",
            content=b"foto",
            headers={"content-type": "image/jpeg"},
        )
    assert response.status_code == 503
    assert "apagada" in response.json()["detail"]


def test_tanda_sobre_compra_inexistente_da_404(client):
    response = client.post(
        "/compras/999999/tanda", content=b"foto", headers={"content-type": "image/jpeg"}
    )
    assert response.status_code == 404


# --- POST /compras/{id}/ejemplares: confirma, guarda ------------------------


def test_confirmar_dos_ejemplares_los_guarda(client, clean_db):
    purchase_id = _crear_compra(client)
    response = client.post(
        f"/compras/{purchase_id}/ejemplares",
        json={
            "ejemplares": [
                {"card_id": "me02.5-020", "variant_id": "normal"},
                {"card_id": "me02.5-039", "variant_id": "normal", "condition": "NM"},
            ]
        },
    )
    assert response.status_code == 200
    ids = response.json()["ids"]
    assert len(ids) == 2

    filas = clean_db.execute(
        "select id, purchase_id, card_id, variant_id, capture_status, is_bulk "
        "from app.owned_copy where purchase_id = %s order by id",
        (purchase_id,),
    ).fetchall()
    assert len(filas) == 2
    assert {f["card_id"] for f in filas} == {"me02.5-020", "me02.5-039"}
    assert all(f["capture_status"] == "listo" for f in filas)
    assert all(f["is_bulk"] is False for f in filas)


def test_confirmar_una_carta_desconocida_da_422_y_no_guarda_nada(client, clean_db):
    purchase_id = _crear_compra(client)
    response = client.post(
        f"/compras/{purchase_id}/ejemplares",
        json={"ejemplares": [{"card_id": "no-existe-999", "variant_id": "normal"}]},
    )
    assert response.status_code == 422
    total = clean_db.execute(
        "select count(*) as n from app.owned_copy where purchase_id = %s", (purchase_id,)
    ).fetchone()["n"]
    assert total == 0


def test_confirmar_ejemplares_sobre_compra_inexistente_da_404(client):
    response = client.post(
        "/compras/999999/ejemplares",
        json={"ejemplares": [{"card_id": "me02.5-020", "variant_id": "normal"}]},
    )
    assert response.status_code == 404


# --- POST /compras/{id}/relleno: bulk sin carta ni foto ---------------------


def test_relleno_crea_n_bulk_sin_carta(client, clean_db):
    purchase_id = _crear_compra(client)
    response = client.post(f"/compras/{purchase_id}/relleno", json={"cantidad": 4})
    assert response.status_code == 200
    ids = response.json()["ids"]
    assert len(ids) == 4

    filas = clean_db.execute(
        "select card_id, is_bulk, photo_front_url, capture_status from app.owned_copy "
        "where purchase_id = %s",
        (purchase_id,),
    ).fetchall()
    assert len(filas) == 4
    assert all(f["card_id"] is None for f in filas)
    assert all(f["is_bulk"] is True for f in filas)
    assert all(f["photo_front_url"] is None for f in filas)


def test_relleno_con_cantidad_invalida_da_422(client):
    purchase_id = _crear_compra(client)
    response = client.post(f"/compras/{purchase_id}/relleno", json={"cantidad": 0})
    assert response.status_code == 422


# --- POST /compras/{id}/repartir --------------------------------------------


def _confirmar(client, purchase_id, ejemplares) -> list[int]:
    response = client.post(f"/compras/{purchase_id}/ejemplares", json={"ejemplares": ejemplares})
    assert response.status_code == 200
    return response.json()["ids"]


def test_repartir_por_valor_de_mercado_cuadra_con_el_total(client):
    # Charmander $5.00, Psyduck $15.00 -- proporción 1:3 de un total de 40.
    purchase_id = _crear_compra(client, total="40.00")
    _confirmar(
        client,
        purchase_id,
        [
            {"card_id": "me02.5-020", "variant_id": "normal"},
            {"card_id": "me02.5-039", "variant_id": "normal"},
        ],
    )

    response = client.post(f"/compras/{purchase_id}/repartir", json={"method": "market_value"})

    assert response.status_code == 200
    body = response.json()
    assert body["total_usd"] == 40.00
    montos = {a["ejemplar_id"]: a["costo_usd"] for a in body["asignaciones"]}
    assert sum(montos.values()) == pytest.approx(40.00)
    valores = sorted(montos.values())
    assert valores == [10.0, 30.0]


def test_repartir_dos_veces_con_metodos_distintos_no_cambia_el_total(client):
    purchase_id = _crear_compra(client, total="40.00")
    _confirmar(
        client,
        purchase_id,
        [
            {"card_id": "me02.5-020", "variant_id": "normal"},
            {"card_id": "me02.5-039", "variant_id": "normal"},
        ],
    )

    por_valor = client.post(f"/compras/{purchase_id}/repartir", json={"method": "market_value"})
    por_igual = client.post(f"/compras/{purchase_id}/repartir", json={"method": "equal"})

    assert por_valor.json()["total_usd"] == 40.00
    assert por_igual.json()["total_usd"] == 40.00
    assert sum(a["costo_usd"] for a in por_igual.json()["asignaciones"]) == pytest.approx(40.00)

    compra = client.get(f"/compras/{purchase_id}").json()
    assert compra["total_usd"] == 40.00
    assert compra["allocation_method"] == "equal"


def test_repartir_una_carta_bulk_le_da_cero_y_las_demas_absorben_todo(client):
    purchase_id = _crear_compra(client, total="40.00")
    _confirmar(
        client,
        purchase_id,
        [
            {"card_id": "me02.5-020", "variant_id": "normal"},
            {"card_id": "me02.5-039", "variant_id": "normal"},
        ],
    )
    relleno_response = client.post(f"/compras/{purchase_id}/relleno", json={"cantidad": 1})
    bulk_id = relleno_response.json()["ids"][0]

    response = client.post(f"/compras/{purchase_id}/repartir", json={"method": "market_value"})

    assert response.status_code == 200
    montos = {a["ejemplar_id"]: a["costo_usd"] for a in response.json()["asignaciones"]}
    assert montos[bulk_id] == 0.0
    assert sum(montos.values()) == pytest.approx(40.00)


def test_repartir_sin_precio_de_mercado_da_422_con_mensaje_explicito(client):
    purchase_id = _crear_compra(client, total="10.00")
    _confirmar(client, purchase_id, [{"card_id": "me02.5-010", "variant_id": "normal"}])

    response = client.post(f"/compras/{purchase_id}/repartir", json={"method": "market_value"})

    assert response.status_code == 422
    assert "precio de mercado" in response.json()["detail"]


def test_repartir_manual_que_no_cuadra_da_422_con_el_residuo(client):
    purchase_id = _crear_compra(client, total="10.00")
    ids = _confirmar(client, purchase_id, [{"card_id": "me02.5-020", "variant_id": "normal"}])

    response = client.post(
        f"/compras/{purchase_id}/repartir",
        json={"method": "manual", "costos": {str(ids[0]): "3.00"}},
    )

    assert response.status_code == 422
    assert "residuo" in response.json()["detail"]


def test_repartir_sobre_compra_inexistente_da_404(client):
    response = client.post("/compras/999999/repartir", json={"method": "equal"})
    assert response.status_code == 404


# --- GET /compras/{id} -------------------------------------------------------


def test_get_compra_trae_sus_ejemplares_con_costo(client):
    purchase_id = _crear_compra(client, total="20.00")
    _confirmar(client, purchase_id, [{"card_id": "me02.5-020", "variant_id": "normal"}])
    client.post(f"/compras/{purchase_id}/repartir", json={"method": "equal"})

    response = client.get(f"/compras/{purchase_id}")

    assert response.status_code == 200
    body = response.json()
    assert len(body["ejemplares"]) == 1
    assert body["ejemplares"][0]["costo_usd"] == 20.00
    assert body["ejemplares"][0]["card_id"] == "me02.5-020"
