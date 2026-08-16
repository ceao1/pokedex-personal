import pytest
from fastapi.testclient import TestClient

from pokedex.api.main import app
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


def test_un_dex_inexistente_devuelve_404(sembrado):
    with TestClient(app) as client:
        assert client.get("/pokedex/999").status_code == 404


def test_get_wishlist_devuelve_los_items(sembrado):
    with TestClient(app) as client:
        body = client.get("/wishlist").json()
    assert len(body) == 1
    assert body[0]["source_option"] == "opcion_1"
