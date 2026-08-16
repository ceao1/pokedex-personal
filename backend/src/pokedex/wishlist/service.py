"""Import del Excel: parsear, resolver contra el catálogo, persistir.

Reejecutable: los upserts son idempotentes y las correcciones manuales
(`auto_resolved = false`) sobreviven al reimport.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

from psycopg import Connection
from pydantic import BaseModel

from . import repository
from .excel import parse_workbook
from .models import GalleryRow, WishlistItemIn
from .resolver import OptionResolver

ConnFactory = Callable[[], AbstractContextManager[Connection]]


class ImportSummary(BaseModel):
    pokemon: int = 0
    items_creados: int = 0
    items_actualizados: int = 0
    sin_resolver: int = 0


class ImportService:
    def __init__(self, catalog, conn_factory: ConnFactory) -> None:
        self._catalog = catalog
        self._conn_factory = conn_factory

    async def import_workbook(self, path: str | Path) -> ImportSummary:
        rows, gallery = parse_workbook(path)
        resolver = OptionResolver(self._catalog)
        summary = ImportSummary()

        with self._conn_factory() as conn:
            antes = self._contar_items(conn)

            for row in rows:
                repository.upsert_pokemon(conn, row.dex_number, row.pokemon_name)
                summary.pokemon += 1

                for resolved in await resolver.resolve_row(row):
                    if resolved.card_id is None:
                        summary.sin_resolver += 1
                    repository.upsert_wishlist_item(
                        conn,
                        WishlistItemIn(
                            dex_number=row.dex_number,
                            card_id=resolved.card_id,
                            variant_label=resolved.variant_label,
                            raw_text=resolved.raw_text,
                            source_option=resolved.source_option,
                            auto_resolved=resolved.auto_resolved,
                            reference_value_usd=resolved.reference_value_usd,
                        ),
                    )

            for gallery_row in gallery:
                self._marcar_favorito(conn, gallery_row)

            conn.commit()
            despues = self._contar_items(conn)

        summary.items_creados = despues - antes
        summary.items_actualizados = antes
        return summary

    def _marcar_favorito(self, conn: Connection, gallery_row: GalleryRow) -> None:
        """La galería no crea items nuevos si la carta ya está como opción:
        le pone la marca de favorito. Trece de sus filas dicen literalmente
        'Ya está en tu Opción 2'."""
        repository.upsert_wishlist_item(
            conn,
            WishlistItemIn(
                dex_number=gallery_row.dex_number,
                card_id=None,
                variant_label=None,
                raw_text=gallery_row.raw_text,
                source_option="galeria",
                is_favorite=True,
                reference_value_usd=gallery_row.reference_value_usd,
            ),
        )

    @staticmethod
    def _contar_items(conn: Connection) -> int:
        return conn.execute("select count(*) as n from app.wishlist_item").fetchone()["n"]
