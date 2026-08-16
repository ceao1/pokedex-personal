"""Espejo perezoso del catálogo.

La primera vez que se pide una carta se trae de TCGdex y se copia a la base
con el precio del momento; a partir de ahí se sirve local. Esto es lo que el
spec llama espejo perezoso (D7): el cache ES el espejo, así que no hace falta
self-hostear el catálogo completo.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager

from psycopg import Connection

from . import repository
from .models import Card, CardRef, SetRef
from .ports import CatalogPort

# `pool.connection` cumple esta firma tal cual.
ConnFactory = Callable[[], AbstractContextManager[Connection]]


class CatalogService:
    def __init__(self, catalog: CatalogPort, conn_factory: ConnFactory) -> None:
        self._catalog = catalog
        self._conn_factory = conn_factory
        # `CardRef` es demasiado liviano para espejarse en `app.card` (le
        # faltan `raw`, `set_name`, etc.), así que el cache de este listado
        # vive en memoria, por instancia, en vez de en la base como el resto
        # del espejo. Evita repetir la llamada de red por cada Pokémon de un
        # mismo set vintage.
        self._set_cache: dict[str, list[CardRef]] = {}
        # Los 218 sets de TCGdex no cambian dentro de la vida de esta
        # instancia; sin este cache, cada identificación por foto repetiría
        # la llamada completa a `GET /sets` (ver `recognition.resolver`).
        self._sets_cache: list[SetRef] | None = None

    async def get_card(self, card_id: str) -> Card | None:
        with self._conn_factory() as conn:
            local = repository.get_card(conn, card_id)
            if local is not None:
                return local

        remote = await self._catalog.get_card(card_id)
        if remote is None:
            return None

        with self._conn_factory() as conn:
            repository.upsert_card(conn, remote)
        return remote

    async def list_set_cards(self, set_id: str) -> list[CardRef]:
        if set_id not in self._set_cache:
            self._set_cache[set_id] = await self._catalog.list_set_cards(set_id)
        return self._set_cache[set_id]

    async def list_sets(self) -> list[SetRef]:
        if self._sets_cache is None:
            self._sets_cache = await self._catalog.list_sets()
        return self._sets_cache

    async def find_by_set_and_number(self, set_id: str, local_id: str) -> Card | None:
        with self._conn_factory() as conn:
            local = repository.find_by_set_and_number(conn, set_id, local_id)
            if local is not None:
                return local

        remote = await self._catalog.find_by_set_and_number(set_id, local_id)
        if remote is None:
            return None

        with self._conn_factory() as conn:
            repository.upsert_card(conn, remote)
        return remote
