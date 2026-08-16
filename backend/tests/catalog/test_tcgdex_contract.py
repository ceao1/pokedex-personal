"""Verifica que la API real de TCGdex sigue teniendo la forma que asumimos.

Excluido de la suite por defecto (marca `contract`). Correr a mano:
    uv run pytest -m contract -v
"""

import httpx
import pytest

from pokedex.catalog.pricing import TCGPLAYER_SUBKEY_BY_TYPE
from pokedex.catalog.tcgdex import TcgdexCatalog

pytestmark = pytest.mark.contract

BASE_URL = "https://api.tcgdex.net/v2/en"


async def _get(card_id: str):
    async with httpx.AsyncClient(timeout=20) as client:
        return await TcgdexCatalog(BASE_URL, client).get_card(card_id)


async def test_el_payload_sigue_trayendo_variantes_con_id():
    card = await _get("sv03.5-001")
    assert card is not None
    assert card.variants, "variants_detailed desapareció del payload"
    assert all(v.id for v in card.variants), "las variantes perdieron variantId"


async def test_al_menos_una_variante_moderna_sigue_teniendo_precio():
    card = await _get("sv03.5-001")
    con_precio = [v for v in card.variants if v.price_usd is not None]
    assert con_precio, (
        "ninguna variante trajo precio: o TCGdex dejó de exponer pricing, "
        "o cambiaron las sub-claves de tcgplayer"
    )


async def test_las_subclaves_de_tcgplayer_siguen_llamandose_igual():
    card = await _get("sv03.5-001")
    vistas = set()
    for variant in card.variants:
        block = (variant.raw.get("pricing") or {}).get("tcgplayer") or {}
        vistas.update(k for k in block if k not in {"unit", "updated"})
    conocidas = set(TCGPLAYER_SUBKEY_BY_TYPE.values())
    assert vistas & conocidas, f"sub-claves desconocidas: {vistas}"


async def test_la_url_de_imagen_construida_responde_200():
    card = await _get("sv03.5-199")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.head(card.image_url)
    assert response.status_code == 200, f"{card.image_url} devolvió {response.status_code}"


async def test_una_carta_inexistente_devuelve_none():
    assert await _get("set-que-no-existe-999") is None
