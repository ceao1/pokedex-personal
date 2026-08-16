"""Siembra sin Excel: el checklist de los 151 y su carta por defecto.

Reemplaza al import del Excel (spec original, retirado por pedido del
dueño: "ya sabes cuáles son [los 151], no necesitas nada del excel"). Los 151
nombres viven en código (`catalog.pokemon_151.los_151`), no en un archivo, y
la carta por defecto de cada Pokémon es `sv03.5-{dex:03d}` -- en el set
`sv03.5` (el set "151" de TCGdex) el número de carta 001..151 ES el número
de dex (contrato verificado en `tests/catalog/test_pokemon_151_contract.py`).

Reejecutable: sembrar el checklist es un upsert por `dex_number`, y espejar
una carta ya espejada no vuelve a pedirla a TCGdex (`CatalogService.get_card`
sirve la copia local). Sirve como camino de recuperación después de un
reseteo de la base: correrlo de nuevo no duplica nada.

Degradable, igual que el import viejo: el checklist (`app.pokemon`) se
siembra completo pase lo que pase con el catálogo, porque los 151 nombres
son un hecho fijo del código, no un dato que dependa de la red. Si TCGdex
está inalcanzable para alguna carta puntual, esa carta se salta -- nunca se
aborta la corrida completa por una sola falla de red.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager

import httpx
from psycopg import Connection
from pydantic import BaseModel

from pokedex.catalog.errors import CATALOG_NETWORK_ERRORS, es_error_de_servidor
from pokedex.catalog.pokemon_151 import los_151
from pokedex.catalog.service import CatalogService

from . import repository

ConnFactory = Callable[[], AbstractContextManager[Connection]]

SET_151 = "sv03.5"


class SeedSummary(BaseModel):
    pokemon: int = 0
    cartas_espejadas: int = 0
    # Cartas que no se pudieron espejar porque TCGdex estaba inalcanzable
    # (timeout, error de conexión, 5xx) -- no porque el catálogo haya
    # respondido "no existe". Ver `catalog.errors`.
    catalogo_inalcanzable: int = 0


def default_card_id(dex_number: int) -> str:
    """La carta por defecto de un Pokémon: `sv03.5-{dex:03d}`."""
    return f"{SET_151}-{dex_number:03d}"


class SeedService:
    def __init__(self, catalog: CatalogService, conn_factory: ConnFactory) -> None:
        self._catalog = catalog
        self._conn_factory = conn_factory

    async def sembrar(self) -> SeedSummary:
        summary = SeedSummary()

        # El checklist se siembra completo y se commitea antes de tocar la
        # red: los 151 nombres son un hecho fijo del código, así que ni un
        # catálogo completamente caído puede dejar `app.pokemon` vacío.
        with self._conn_factory() as conn:
            for dex_number, nombre in los_151():
                repository.upsert_pokemon(conn, dex_number, nombre)
                summary.pokemon += 1
            conn.commit()

        for dex_number, _nombre in los_151():
            card_id = default_card_id(dex_number)
            try:
                carta = await self._catalog.get_card(card_id)
            except CATALOG_NETWORK_ERRORS:
                summary.catalogo_inalcanzable += 1
                continue
            except httpx.HTTPStatusError as exc:
                if not es_error_de_servidor(exc):
                    raise
                summary.catalogo_inalcanzable += 1
                continue
            if carta is not None:
                summary.cartas_espejadas += 1

        return summary
