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
    """Cada sub-clave de `TCGPLAYER_SUBKEY_BY_TYPE` tiene que verse al menos
    una vez en la API real. `sv03.5-001` (Bulbasaur) solo expone `normal` y
    `reverse-holofoil`; nunca trae `holofoil`. Probar solo esa carta no
    detectaría un cambio de nombre en `holofoil`, la sub-clave de la que
    dependen todos los precios holo y vintage. Se agrega `sv03.5-199`
    (Charizard ex, única variante holo) para cubrirla también."""
    bulbasaur = await _get("sv03.5-001")
    charizard_ex = await _get("sv03.5-199")

    vistas_por_carta: dict[str, set[str]] = {}
    for card in (bulbasaur, charizard_ex):
        claves = set()
        for variant in card.variants:
            block = (variant.raw.get("pricing") or {}).get("tcgplayer") or {}
            claves.update(k for k in block if k not in {"unit", "updated"})
        vistas_por_carta[card.id] = claves

    vistas = set().union(*vistas_por_carta.values())
    esperadas = set(TCGPLAYER_SUBKEY_BY_TYPE.values())
    faltantes = esperadas - vistas
    assert not faltantes, (
        f"sub-claves ausentes en la API real: {faltantes}. Vistas por carta: {vistas_por_carta}"
    )


async def test_la_url_de_imagen_construida_responde_200():
    card = await _get("sv03.5-199")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.head(card.image_url)
    assert response.status_code == 200, f"{card.image_url} devolvió {response.status_code}"


async def test_una_carta_inexistente_devuelve_none():
    assert await _get("set-que-no-existe-999") is None
