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
from .models import Card
from .ports import CatalogPort

# `pool.connection` cumple esta firma tal cual.
ConnFactory = Callable[[], AbstractContextManager[Connection]]


class CatalogService:
    def __init__(self, catalog: CatalogPort, conn_factory: ConnFactory) -> None:
        self._catalog = catalog
        self._conn_factory = conn_factory

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
