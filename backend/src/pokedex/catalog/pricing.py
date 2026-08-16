"""Extracción del precio de mercado en USD desde un payload de TCGdex.

El bloque `pricing` de TCGdex NO está scopeado a la variante: el mismo objeto
`tcgplayer` se repite idéntico en todas las entradas de `variants_detailed`, y
contiene una sub-clave por tipo de acabado. Hay que elegir la sub-clave según
el `type` de la variante; leer `pricing.tcgplayer.marketPrice` directo no
funciona porque esa clave no existe.

Cardmarket viene en EUR y no se usa: la aplicación trabaja en USD y no tiene
tabla de tipo de cambio.
"""

from decimal import Decimal

TCGPLAYER_SUBKEY_BY_TYPE = {
    "normal": "normal",
    "reverse": "reverse-holofoil",
    "holo": "holofoil",
}


def extract_price_usd(variant: dict) -> Decimal | None:
    """Precio de mercado en USD de una entrada de `variants_detailed`.

    Devuelve None cuando no hay precio disponible, que es un estado válido
    y frecuente en variantes vintage.
    """
    pricing = variant.get("pricing") or {}
    tcgplayer = pricing.get("tcgplayer") or {}

    subkey = TCGPLAYER_SUBKEY_BY_TYPE.get(variant.get("type", ""))
    if subkey is None:
        return None

    block = tcgplayer.get(subkey)
    if not isinstance(block, dict):
        return None

    market_price = block.get("marketPrice")
    if market_price is None:
        return None

    return Decimal(str(market_price))
