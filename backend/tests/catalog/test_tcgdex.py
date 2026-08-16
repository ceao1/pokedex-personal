from datetime import UTC, datetime

import httpx
import pytest
import respx

from pokedex.catalog.tcgdex import TcgdexCatalog, build_image_url, parse_card

from .loaders import load_fixture

BASE_URL = "https://api.tcgdex.example/v2/en"
CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def test_build_image_url_agrega_el_sufijo():
    """El campo `image` de TCGdex es una base sin extensión; sin sufijo da 404."""
    url = build_image_url("https://assets.tcgdex.net/en/sv/sv03.5/199")
    assert url == "https://assets.tcgdex.net/en/sv/sv03.5/199/high.png"


def test_build_image_url_tolera_ausencia():
    assert build_image_url(None) is None


def test_parse_card_extrae_los_campos_del_catalogo():
    card = parse_card(load_fixture("card_sv03.5-199"), CAPTURED_AT)
    assert card.id == "sv03.5-199"
    assert card.name == "Charizard ex"
    assert card.set_id == "sv03.5"
    assert card.set_name == "151"
    assert card.local_id == "199"
    assert card.set_card_count == 165
    assert card.rarity == "Special illustration rare"
    assert card.dex_number == 6
    assert card.image_url.endswith("/high.png")
    assert len(card.variants) == 1


def test_parse_card_sin_dex_id():
    """Entrenadores y energías no tienen dexId."""
    payload = dict(load_fixture("card_sv03.5-199"))
    payload.pop("dexId")
    assert parse_card(payload, CAPTURED_AT).dex_number is None


@respx.mock
async def test_get_card_pide_el_endpoint_correcto():
    route = respx.get(f"{BASE_URL}/cards/sv03.5-199").mock(
        return_value=httpx.Response(200, json=load_fixture("card_sv03.5-199"))
    )
    async with httpx.AsyncClient() as client:
        catalog = TcgdexCatalog(BASE_URL, client)
        card = await catalog.get_card("sv03.5-199")
    assert route.called
    assert card.id == "sv03.5-199"


@respx.mock
async def test_get_card_devuelve_none_si_no_existe():
    respx.get(f"{BASE_URL}/cards/no-existe").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        catalog = TcgdexCatalog(BASE_URL, client)
        assert await catalog.get_card("no-existe") is None


@respx.mock
async def test_find_by_set_and_number_usa_el_endpoint_de_sets():
    route = respx.get(f"{BASE_URL}/sets/sv03.5/001").mock(
        return_value=httpx.Response(200, json=load_fixture("card_sv03.5-001"))
    )
    async with httpx.AsyncClient() as client:
        catalog = TcgdexCatalog(BASE_URL, client)
        card = await catalog.find_by_set_and_number("sv03.5", "001")
    assert route.called
    assert card.id == "sv03.5-001"


@respx.mock
async def test_un_error_del_servidor_se_propaga():
    respx.get(f"{BASE_URL}/cards/x").mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as client:
        catalog = TcgdexCatalog(BASE_URL, client)
        with pytest.raises(httpx.HTTPStatusError):
            await catalog.get_card("x")


@respx.mock
async def test_list_set_cards_devuelve_referencias_livianas():
    respx.get(f"{BASE_URL}/sets/base1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "base1",
                "name": "Base Set",
                "cards": [
                    {
                        "id": "base1-4",
                        "localId": "4",
                        "name": "Charizard",
                        "image": "https://x/4",
                    }
                ],
            },
        )
    )
    async with httpx.AsyncClient() as client:
        refs = await TcgdexCatalog(BASE_URL, client).list_set_cards("base1")
    assert [(r.id, r.local_id, r.name) for r in refs] == [("base1-4", "4", "Charizard")]


@respx.mock
async def test_list_set_cards_de_un_set_inexistente_devuelve_vacio():
    respx.get(f"{BASE_URL}/sets/no-existe").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        assert await TcgdexCatalog(BASE_URL, client).list_set_cards("no-existe") == []


@respx.mock
async def test_get_set_detail_trae_la_abreviatura():
    respx.get(f"{BASE_URL}/sets/me02.5").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "me02.5",
                "name": "Ascended Heroes",
                "cardCount": {"official": 217},
                "abbreviation": {"official": "ASC"},
                "cards": [],
            },
        )
    )
    async with httpx.AsyncClient() as client:
        detail = await TcgdexCatalog(BASE_URL, client).get_set_detail("me02.5")
    assert detail.id == "me02.5"
    assert detail.total == 217
    assert detail.abbreviation == "ASC"


@respx.mock
async def test_get_set_detail_tolera_ausencia_de_abreviatura():
    """Los sets antiguos no traen `abbreviation` -- la carta física tampoco
    la imprime."""
    respx.get(f"{BASE_URL}/sets/base1").mock(
        return_value=httpx.Response(
            200,
            json={"id": "base1", "name": "Base Set", "cardCount": {"official": 102}, "cards": []},
        )
    )
    async with httpx.AsyncClient() as client:
        detail = await TcgdexCatalog(BASE_URL, client).get_set_detail("base1")
    assert detail.abbreviation is None


@respx.mock
async def test_get_set_detail_de_un_set_inexistente_devuelve_none():
    respx.get(f"{BASE_URL}/sets/no-existe").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        assert await TcgdexCatalog(BASE_URL, client).get_set_detail("no-existe") is None


@respx.mock
async def test_list_set_cards_y_get_set_detail_comparten_la_llamada():
    """Mismo endpoint (`GET /sets/{id}`) para las dos necesidades: pedir las
    dos para el mismo set no debe disparar una segunda llamada de red."""
    route = respx.get(f"{BASE_URL}/sets/me02.5").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "me02.5",
                "name": "Ascended Heroes",
                "cardCount": {"official": 217},
                "abbreviation": {"official": "ASC"},
                "cards": [{"id": "me02.5-176", "localId": "176", "name": "Drampa"}],
            },
        )
    )
    async with httpx.AsyncClient() as client:
        catalog = TcgdexCatalog(BASE_URL, client)
        await catalog.get_set_detail("me02.5")
        await catalog.list_set_cards("me02.5")
    assert route.call_count == 1
