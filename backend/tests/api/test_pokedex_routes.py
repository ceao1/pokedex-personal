from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from pokedex.api.main import app
from pokedex.api.routes.pokedex import get_storage
from pokedex.collection.storage import FakeStorage
from pokedex.wishlist import repository
from pokedex.wishlist.models import WishlistItemIn


@pytest.fixture()
def sembrado(clean_db):
    clean_db.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, image_url, rarity, raw)
        values ('sv03.5-001', 'Bulbasaur', 'sv03.5', '151', '001',
                'https://assets.tcgdex.net/en/sv/sv03.5/001/high.png', 'Común', '{}'::jsonb)
        """
    )
    clean_db.execute(
        """
        insert into app.card_variant (id, card_id, type, price_usd, price_captured_at, raw)
        values ('sv03.5-001-normal', 'sv03.5-001', 'normal', 0.25, now(), '{}'::jsonb)
        """
    )
    repository.upsert_pokemon(clean_db, 1, "Bulbasaur")
    repository.upsert_pokemon(clean_db, 2, "Ivysaur")
    repository.upsert_wishlist_item(
        clean_db,
        WishlistItemIn(
            dex_number=1,
            card_id="sv03.5-001",
            variant_label="normal",
            raw_text="Bulbasaur 001/165",
            source_option="opcion_1",
        ),
    )
    clean_db.commit()
    return clean_db


def test_get_pokedex_devuelve_todos_los_sembrados(sembrado):
    with TestClient(app) as client:
        response = client.get("/pokedex")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["dex_number"] == 1
    assert body[0]["name"] == "Bulbasaur"


def test_get_pokedex_incluye_el_conteo_de_wishlist(sembrado):
    with TestClient(app) as client:
        body = client.get("/pokedex").json()
    por_dex = {p["dex_number"]: p for p in body}
    assert por_dex[1]["wishlist_count"] == 1
    assert por_dex[2]["wishlist_count"] == 0


def test_get_pokedex_trae_el_arte_de_la_ruta_preferida(sembrado):
    """La grilla del binder dibuja la carta real que se persigue."""
    with TestClient(app) as client:
        body = client.get("/pokedex").json()
    por_dex = {p["dex_number"]: p for p in body}
    assert por_dex[1]["primary_image_url"].endswith("/high.png")
    assert por_dex[1]["primary_card_name"] == "Bulbasaur"
    assert por_dex[2]["primary_image_url"] is None


def test_get_pokedex_trae_el_precio_como_float(sembrado):
    """`numeric` de Postgres llega como Decimal; JSON exige float en el borde
    HTTP. La wishlist_count no debe inflarse por el join con card_variant."""
    with TestClient(app) as client:
        body = client.get("/pokedex").json()
    por_dex = {p["dex_number"]: p for p in body}
    assert por_dex[1]["primary_price_usd"] == 0.25
    assert isinstance(por_dex[1]["primary_price_usd"], float)
    assert por_dex[1]["wishlist_count"] == 1


def test_get_pokedex_trae_la_fecha_del_precio_congelado(sembrado):
    """Spec §11/§15: todo precio de mercado debe traer la fecha en que se
    congeló, porque nunca se refresca (D5). Sin fecha es un dato que el
    sistema no puede sostener."""
    with TestClient(app) as client:
        body = client.get("/pokedex").json()
    por_dex = {p["dex_number"]: p for p in body}
    fecha = por_dex[1]["primary_price_captured_at"]
    assert fecha is not None
    assert isinstance(fecha, str)
    # ISO 8601, igual que el resto de la API -- debe poder re-parsearse.
    datetime.fromisoformat(fecha)
    assert por_dex[2]["primary_price_captured_at"] is None


def test_el_contador_de_conseguidos_no_miente(sembrado):
    """`owned_count` es lo que el dashboard muestra como progreso del 151.
    Tener rutas de caza no es tener la carta: con una wishlist sembrada y sin
    captura, el progreso honesto es cero."""
    with TestClient(app) as client:
        body = client.get("/pokedex").json()
    assert all(p["owned_count"] == 0 for p in body)
    assert any(p["wishlist_count"] > 0 for p in body)


def test_get_pokedex_de_un_pokemon_trae_sus_opciones(sembrado):
    with TestClient(app) as client:
        response = client.get("/pokedex/1")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Bulbasaur"
    assert len(body["options"]) == 1
    assert body["options"][0]["card_name"] == "Bulbasaur"
    assert body["options"][0]["image_url"].endswith("/high.png")
    assert body["options"][0]["price_usd"] == 0.25


def test_get_pokemon_detail_trae_la_fecha_del_precio_por_opcion(sembrado):
    with TestClient(app) as client:
        body = client.get("/pokedex/1").json()
    fecha = body["options"][0]["price_captured_at"]
    assert fecha is not None
    datetime.fromisoformat(fecha)


def test_un_dex_inexistente_devuelve_404(sembrado):
    with TestClient(app) as client:
        assert client.get("/pokedex/999").status_code == 404


def test_get_wishlist_devuelve_los_items(sembrado):
    with TestClient(app) as client:
        body = client.get("/wishlist").json()
    assert len(body) == 1
    assert body[0]["source_option"] == "opcion_1"


def test_get_wishlist_trae_la_fecha_del_precio(sembrado):
    with TestClient(app) as client:
        body = client.get("/wishlist").json()
    fecha = body[0]["price_captured_at"]
    assert fecha is not None
    datetime.fromisoformat(fecha)


@pytest.fixture()
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture()
def client_con_ejemplares(sembrado, fake_storage):
    """El bucket es privado (decisión de diseño): la suite no puede pegarle a
    Supabase Storage real, así que `get_storage` se sustituye por un fake,
    igual que `test_capture_routes.py` hace con `get_service`."""
    app.dependency_overrides[get_storage] = lambda: fake_storage
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_get_pokedex_de_un_dex_devuelve_tus_ejemplares_con_foto_firmada(
    client_con_ejemplares, sembrado, fake_storage
):
    """`GET /pokedex/4` con dos ejemplares devuelve `copies` con dos
    entradas, cada una con su `photo_url` firmada cuando tiene foto y `null`
    cuando no."""
    sembrado.execute(
        """
        insert into app.pokemon (dex_number, name) values (4, 'Charmander')
        on conflict do nothing
        """
    )
    sembrado.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, dex_number, image_url, raw)
        values ('sv03.5-004', 'Charmander', 'sv03.5', '151', '004', 4,
                'https://x/004/high.png', '{}'::jsonb)
        """
    )
    con_foto = uuid4()
    sin_foto = uuid4()
    sembrado.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, photo_front_url, notes)
        values (%s, 'sv03.5-004', %s, 'con foto')
        """,
        (con_foto, f"{con_foto}/front.jpg"),
    )
    sembrado.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, notes)
        values (%s, 'sv03.5-004', 'sin foto')
        """,
        (sin_foto,),
    )
    sembrado.commit()

    response = client_con_ejemplares.get("/pokedex/4")
    assert response.status_code == 200
    body = response.json()
    assert len(body["copies"]) == 2
    por_nota = {c["notes"]: c for c in body["copies"]}
    assert por_nota["con foto"]["photo_url"] is not None
    assert por_nota["con foto"]["photo_url"].startswith("https://fake.storage.test/download/")
    assert por_nota["sin foto"]["photo_url"] is None
    # Firmado en lote: una sola llamada a la red por la ficha completa, no
    # una por ejemplar dentro de un bucle sin control.
    assert fake_storage.batch_calls == [[f"{con_foto}/front.jpg"]]


def test_get_otras_cartas_devuelve_ejemplares_fuera_del_151_con_foto_firmada(
    client_con_ejemplares, sembrado, fake_storage
):
    sembrado.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, dex_number, raw)
        values ('me02.5-008', 'Chikorita', 'me02.5', 'Ascended Heroes', '008', 152, '{}'::jsonb)
        """
    )
    con_foto = uuid4()
    sembrado.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, photo_front_url, notes)
        values (%s, 'me02.5-008', %s, 'Chikorita fuera del proyecto')
        """,
        (con_foto, f"{con_foto}/front.jpg"),
    )
    sembrado.commit()

    response = client_con_ejemplares.get("/otras-cartas")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["card_name"] == "Chikorita"
    assert body[0]["dex_number"] == 152
    assert body[0]["photo_url"] is not None
    assert body[0]["photo_url"].startswith("https://fake.storage.test/download/")


def test_get_otras_cartas_no_incluye_un_ejemplar_del_binder(client_con_ejemplares, sembrado):
    sembrado.execute(
        "insert into app.pokemon (dex_number, name) values (4, 'Charmander') on conflict do nothing"
    )
    sembrado.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, dex_number, raw)
        values ('sv03.5-004', 'Charmander', 'sv03.5', '151', '004', 4, '{}'::jsonb)
        """
    )
    sembrado.execute(
        "insert into app.owned_copy (client_draft_id, card_id) values (%s, 'sv03.5-004')",
        (uuid4(),),
    )
    sembrado.commit()

    response = client_con_ejemplares.get("/otras-cartas")
    assert response.status_code == 200
    assert response.json() == []


def test_get_otras_cartas_un_error_al_firmar_no_la_revienta(
    client_con_ejemplares, sembrado, fake_storage
):
    """Mismo criterio que la ficha: si firmar falla, la fila se devuelve
    igual con `photo_url: null` en vez de un 500."""
    sembrado.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, dex_number, raw)
        values ('me02.5-008', 'Chikorita', 'me02.5', 'Ascended Heroes', '008', 152, '{}'::jsonb)
        """
    )
    draft = uuid4()
    sembrado.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, photo_front_url)
        values (%s, 'me02.5-008', %s)
        """,
        (draft, f"{draft}/front.jpg"),
    )
    sembrado.commit()
    fake_storage.fallar_firma_de.add(f"{draft}/front.jpg")

    response = client_con_ejemplares.get("/otras-cartas")
    assert response.status_code == 200
    assert response.json()[0]["photo_url"] is None


def test_un_error_al_firmar_no_revienta_la_ficha(client_con_ejemplares, sembrado, fake_storage):
    """La foto es decoración de esta pantalla, los datos no: si firmar falla,
    el ejemplar se devuelve con `photo_url: null` en vez de un 500."""
    sembrado.execute(
        "insert into app.pokemon (dex_number, name) values (4, 'Charmander') on conflict do nothing"
    )
    sembrado.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, dex_number, image_url, raw)
        values ('sv03.5-004', 'Charmander', 'sv03.5', '151', '004', 4,
                'https://x/004/high.png', '{}'::jsonb)
        """
    )
    draft = uuid4()
    sembrado.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, photo_front_url)
        values (%s, 'sv03.5-004', %s)
        """,
        (draft, f"{draft}/front.jpg"),
    )
    sembrado.commit()
    fake_storage.fallar_firma_de.add(f"{draft}/front.jpg")

    response = client_con_ejemplares.get("/pokedex/4")
    assert response.status_code == 200
    assert response.json()["copies"][0]["photo_url"] is None
