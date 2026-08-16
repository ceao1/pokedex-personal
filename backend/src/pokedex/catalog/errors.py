"""Catálogo inalcanzable vs. catálogo que respondió "no existe".

Un timeout, un error de conexión o un 5xx significan que TCGdex no pudo
contestar la pregunta -- muy distinto de un 404 (que la adaptación de TCGdex
ya traduce a `None`, una respuesta real). Confundir las dos cosas es lo que
causaba que una corrida con la red caída guardara filas "sin resolver" que
después, al reintentar, se duplicaban en vez de completarse (ver
`wishlist/seed.py`).

Vivía en `wishlist/resolver.py` (el import del Excel, ya retirado); se muda
acá porque `catalog` es el paquete correcto para una distinción sobre
errores de red del catálogo, y tanto la siembra (`wishlist/seed.py`) como
cualquier otro llamador de `CatalogPort` la necesitan.
"""

import httpx

CATALOG_NETWORK_ERRORS = (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout)


def es_error_de_servidor(exc: httpx.HTTPStatusError) -> bool:
    return exc.response.status_code >= 500
