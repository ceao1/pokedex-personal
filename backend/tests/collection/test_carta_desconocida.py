"""Guardar una carta que el catálogo no conoce da un mensaje, no un 500.

Antes, un `card_id` inexistente llegaba hasta la clave foránea de Postgres y
salía como 500 con la violación en crudo. Peor aún: el ejemplar quedaba a
medias y el cliente no tenía forma de saber si el problema era su dato o el
servidor.

Los dos casos se distinguen a propósito. "La carta no existe" se arregla
corrigiendo el set o el número; "no pude comprobarlo" se arregla esperando.
Decirle al dueño que corrija un set que estaba bien es peor que no decir nada.
"""

from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from pokedex.api.main import app
from pokedex.api.routes.capture import get_service
from pokedex.collection.models import OwnedCopyIn
from pokedex.collection.service import CaptureService, CartaDesconocida
from pokedex.collection.storage import FakeStorage


class CatalogoFalso:
    """Solo conoce las cartas que se le siembran; el resto no existen."""

    def __init__(self, conocidas: dict | None = None, cae: bool = False) -> None:
        self._conocidas = conocidas or {}
        self._cae = cae
        self.consultas: list[str] = []

    async def get_card(self, card_id: str):
        self.consultas.append(card_id)
        if self._cae:
            raise httpx.ConnectTimeout("el catálogo no responde")
        return self._conocidas.get(card_id)


def _factory(conn):
    @contextmanager
    def factory():
        yield conn

    return factory


async def test_una_carta_inexistente_no_llega_a_la_base(clean_db):
    """El servicio corta antes: la clave foránea es la red, no la puerta."""
    catalogo = CatalogoFalso()
    service = CaptureService(FakeStorage(), _factory(clean_db), catalogo)
    draft = uuid4()
    await service.iniciar_captura(draft)
    await service.marcar_fotos_subidas(draft)

    with pytest.raises(CartaDesconocida) as exc:
        await service.registrar(draft, OwnedCopyIn(card_id="no-existe-999"))

    assert exc.value.card_id == "no-existe-999"
    assert exc.value.catalogo_inalcanzable is False
    assert catalogo.consultas == ["no-existe-999"]


async def test_un_catalogo_caido_no_se_confunde_con_una_carta_que_no_existe(clean_db):
    catalogo = CatalogoFalso(cae=True)
    service = CaptureService(FakeStorage(), _factory(clean_db), catalogo)
    draft = uuid4()
    await service.iniciar_captura(draft)
    await service.marcar_fotos_subidas(draft)

    with pytest.raises(CartaDesconocida) as exc:
        await service.registrar(draft, OwnedCopyIn(card_id="sv03.5-001"))

    assert exc.value.catalogo_inalcanzable is True


async def test_un_patch_sin_carta_no_consulta_el_catalogo(clean_db):
    """Cambiar solo el precio no tiene por qué tocar la red."""
    catalogo = CatalogoFalso()
    service = CaptureService(FakeStorage(), _factory(clean_db), catalogo)
    draft = uuid4()
    await service.iniciar_captura(draft)
    await service.marcar_fotos_subidas(draft)

    await service.registrar(draft, OwnedCopyIn(condition="NM"))

    assert catalogo.consultas == []


def _cliente(conn, catalogo):
    app.dependency_overrides[get_service] = lambda: CaptureService(
        FakeStorage(), _factory(conn), catalogo
    )
    return TestClient(app)


def test_la_api_responde_422_y_dice_que_revisar(clean_db):
    with _cliente(clean_db, CatalogoFalso()) as client:
        draft = str(uuid4())
        client.post("/captures", json={"client_draft_id": draft})
        client.post(f"/captures/{draft}/photo-uploaded")
        respuesta = client.patch(f"/captures/{draft}", json={"card_id": "sv03.5-999"})
    app.dependency_overrides.clear()

    assert respuesta.status_code == 422
    detalle = respuesta.json()["detail"]
    assert "sv03.5-999" in detalle, "el mensaje debe nombrar la carta"
    assert "set" in detalle.lower() and "número" in detalle.lower()


def test_la_api_responde_503_cuando_no_pudo_comprobarlo(clean_db):
    with _cliente(clean_db, CatalogoFalso(cae=True)) as client:
        draft = str(uuid4())
        client.post("/captures", json={"client_draft_id": draft})
        client.post(f"/captures/{draft}/photo-uploaded")
        respuesta = client.patch(f"/captures/{draft}", json={"card_id": "sv03.5-001"})
    app.dependency_overrides.clear()

    assert respuesta.status_code == 503
    detalle = respuesta.json()["detail"]
    assert "no se guardó nada" in detalle.lower(), "hay que decir que no quedó a medias"
    assert "revisa" not in detalle.lower(), "no pedirle que corrija un dato que puede estar bien"


def test_ninguna_de_las_dos_respuestas_filtra_las_tripas_de_postgres(clean_db):
    for catalogo in (CatalogoFalso(), CatalogoFalso(cae=True)):
        with _cliente(clean_db, catalogo) as client:
            draft = str(uuid4())
            client.post("/captures", json={"client_draft_id": draft})
            client.post(f"/captures/{draft}/photo-uploaded")
            respuesta = client.patch(f"/captures/{draft}", json={"card_id": "sv03.5-777"})
        app.dependency_overrides.clear()
        detalle = respuesta.json()["detail"].lower()
        for filtracion in ("foreign key", "violates", "psycopg", "traceback", "owned_copy"):
            assert filtracion not in detalle, f"el mensaje filtra {filtracion!r}"
