"""Import del Excel: parsear, resolver contra el catálogo, persistir.

Reejecutable: los upserts son idempotentes y las correcciones manuales
(`auto_resolved = false`) sobreviven al reimport. Degradable: si el catálogo
está inalcanzable, el checklist (`app.pokemon`) igual se siembra desde el
Excel -- que es data local y no necesita red -- y las opciones que no se
pudieron preguntar se saltan en vez de guardarse a medias.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

import httpx
from psycopg import Connection
from pydantic import BaseModel

from . import repository
from .excel import parse_workbook
from .models import GalleryRow, WishlistItemIn
from .resolver import CATALOG_NETWORK_ERRORS, OptionResolver, es_error_de_servidor

ConnFactory = Callable[[], AbstractContextManager[Connection]]


class ImportSummary(BaseModel):
    pokemon: int = 0
    items_creados: int = 0
    items_actualizados: int = 0
    sin_resolver: int = 0
    # Opciones que no se guardaron porque el catálogo estaba inalcanzable
    # (timeout, error de conexión, 5xx) -- no porque hayan resuelto "no
    # existe". Ver el docstring de `ResolvedOption.unreachable`.
    catalogo_inalcanzable: int = 0


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
                # Se siembra pase lo que pase con el catálogo: el dex number
                # y el nombre vienen del Excel, no de TCGdex. Que la red esté
                # caída no puede dejar el checklist vacío.
                repository.upsert_pokemon(conn, row.dex_number, row.pokemon_name)
                summary.pokemon += 1

                for resolved in await resolver.resolve_row(row):
                    if resolved.unreachable:
                        # El catálogo no pudo responder esta pregunta -- no
                        # es que haya dicho "no existe". No se guarda nada:
                        # un item sin resolver se llavea por
                        # (dex_number, raw_text), y si se guardara así, una
                        # corrida posterior que sí resuelva insertaría una
                        # fila *nueva* (llaveada por card_id/variant_label)
                        # en vez de completar esta, dejando la fila vieja
                        # como fantasma para siempre.
                        summary.catalogo_inalcanzable += 1
                        continue
                    if resolved.card_id is not None:
                        espejada = await self._asegurar_espejo(resolved.card_id, cartas_vistas)
                        if not espejada:
                            # Resolvió, pero el catálogo se cayó justo al
                            # intentar espejar la carta. Mismo tratamiento:
                            # sin la carta en app.card el FK la rechazaría,
                            # y contarla como "sin resolver" duplicaría la
                            # fila en el próximo intento.
                            summary.catalogo_inalcanzable += 1
                            continue
                    else:
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
                await self._marcar_favorito(conn, resolver, gallery_row, cartas_vistas, summary)

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
        summary: ImportSummary,
    ) -> None:
        """La galería no crea items nuevos si la carta ya está como opción:
        le pone la marca de favorito encima del item ya existente.

        Para eso hay que resolver el texto de la galería contra el catálogo
        igual que una opción cualquiera: si resuelve a la misma
        `(dex_number, card_id, variant_label)` que ya insertó la opción
        correspondiente, el upsert de `_UPSERT_RESUELTO` cae en el mismo
        conflicto y solo pone `is_favorite`, sin fila nueva. Solo el texto
        que de verdad no resuelve (ej. "Ya está en tu Opción 2", trece de sus
        filas) termina como una fila sin resolver marcada como favorita. Si
        el catálogo estuvo inalcanzable, se salta igual que una opción --
        nada se guarda.
        """
        resolved = await resolver.resolve_gallery_row(gallery_row)
        if resolved.unreachable:
            summary.catalogo_inalcanzable += 1
            return
        if resolved.card_id is not None:
            espejada = await self._asegurar_espejo(resolved.card_id, cartas_vistas)
            if not espejada:
                summary.catalogo_inalcanzable += 1
                return
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

    async def _asegurar_espejo(self, card_id: str, cartas_vistas: set[str]) -> bool:
        """`CatalogService.get_card` devuelve la copia local si ya existe y,
        si no, la trae de TCGdex y la espeja -- idempotente y barato después
        del primer hit. `cartas_vistas` evita repetir la llamada para la
        misma carta dentro de esta corrida.

        Devuelve False si el catálogo resultó inalcanzable al intentar
        espejar -- en ese caso el llamador no debe insertar el
        wishlist_item: el FK lo rechazaría de todos modos, y guardarlo como
        "sin resolver" duplicaría la fila cuando la corrida se repita y sí
        logre espejar (mismo razonamiento que `ResolvedOption.unreachable`).
        """
        if card_id in cartas_vistas:
            return True
        try:
            await self._catalog.get_card(card_id)
        except CATALOG_NETWORK_ERRORS:
            return False
        except httpx.HTTPStatusError as exc:
            if not es_error_de_servidor(exc):
                raise
            return False
        cartas_vistas.add(card_id)
        return True

    @staticmethod
    def _contar_items(conn: Connection) -> int:
        return conn.execute("select count(*) as n from app.wishlist_item").fetchone()["n"]
