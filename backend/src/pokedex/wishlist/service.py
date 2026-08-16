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
        # Opciones 1 y 2 resuelven por `find_by_set_and_number`, que
        # `CatalogService` espeja en `app.card` como efecto secundario. La
        # opción 3 (vintage) resuelve por `list_set_cards`, que devuelve un
        # `CardRef` liviano (id, localId, name) y nunca espeja nada: sin este
        # seguimiento, el FK de `wishlist_item.card_id` rechaza la primera
        # carta vintage que aparece con `ForeignKeyViolation`. Se registra
        # qué card_id ya se garantizó en esta corrida para no repetir la
        # llamada de más -- opciones 1 y 2 frecuentemente apuntan a la misma
        # carta, y el propio espejo local ya dedupe, pero este set lo
        # mantiene rápido sin depender de eso.
        cartas_vistas: set[str] = set()

        with self._conn_factory() as conn:
            antes = self._contar_items(conn)

            for row in rows:
                repository.upsert_pokemon(conn, row.dex_number, row.pokemon_name)
                summary.pokemon += 1

                for resolved in await resolver.resolve_row(row):
                    if resolved.card_id is None:
                        summary.sin_resolver += 1
                    else:
                        await self._asegurar_espejo(resolved.card_id, cartas_vistas)
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
                await self._marcar_favorito(conn, resolver, gallery_row, cartas_vistas)

            conn.commit()
            despues = self._contar_items(conn)

        summary.items_creados = despues - antes
        summary.items_actualizados = antes
        return summary

    async def _marcar_favorito(
        self,
        conn: Connection,
        resolver: OptionResolver,
        gallery_row: GalleryRow,
        cartas_vistas: set[str],
    ) -> None:
        """La galería no crea items nuevos si la carta ya está como opción:
        le pone la marca de favorito encima del item ya existente.

        Para eso hay que resolver el texto de la galería contra el catálogo
        igual que una opción cualquiera: si resuelve a la misma
        `(dex_number, card_id, variant_label)` que ya insertó la opción
        correspondiente, el upsert de `_UPSERT_RESUELTO` cae en el mismo
        conflicto y solo pone `is_favorite`, sin fila nueva. Solo el texto
        que de verdad no resuelve (ej. "Ya está en tu Opción 2", trece de sus
        filas) termina como una fila sin resolver marcada como favorita.
        """
        resolved = await resolver.resolve_gallery_row(gallery_row)
        if resolved.card_id is not None:
            await self._asegurar_espejo(resolved.card_id, cartas_vistas)
        repository.upsert_wishlist_item(
            conn,
            WishlistItemIn(
                dex_number=gallery_row.dex_number,
                card_id=resolved.card_id,
                variant_label=resolved.variant_label,
                raw_text=gallery_row.raw_text,
                source_option="galeria",
                is_favorite=True,
                reference_value_usd=gallery_row.reference_value_usd,
            ),
        )

    async def _asegurar_espejo(self, card_id: str, cartas_vistas: set[str]) -> None:
        """`CatalogService.get_card` devuelve la copia local si ya existe y,
        si no, la trae de TCGdex y la espeja -- idempotente y barato después
        del primer hit. `cartas_vistas` evita repetir la llamada para la
        misma carta dentro de esta corrida."""
        if card_id in cartas_vistas:
            return
        await self._catalog.get_card(card_id)
        cartas_vistas.add(card_id)

    @staticmethod
    def _contar_items(conn: Connection) -> int:
        return conn.execute("select count(*) as n from app.wishlist_item").fetchone()["n"]
