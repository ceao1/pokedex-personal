"""Orquesta las compras: crea la compra, propone una tanda sin guardar
nada, confirma ejemplares, agrega relleno y reparte el costo.

Mismo principio que `collection.service.IdentificationService`: una lectura
del modelo nunca escribe en `owned_copy` por su cuenta. Acá lo mismo aplica
a la tanda completa -- `identificar_tanda` solo lee y devuelve; guardar es
trabajo exclusivo de `confirmar_ejemplares`.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from decimal import Decimal
from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.errors import ForeignKeyViolation
from pydantic import BaseModel

from pokedex.collection.service import CartaDesconocida
from pokedex.collection.storage import StoragePort
from pokedex.recognition.resolver import CardResolver, ResolucionTanda

from . import repository
from .allocation import AllocationError, CopiaReparto
from .allocation import repartir as calcular_reparto
from .models import EjemplarDeCompra, Purchase

ConnFactory = Callable[[], AbstractContextManager[Connection]]


class GeminiNoConfigurado(Exception):
    """La identificación por foto está apagada (falta `GEMINI_API`) -- el
    registro a mano de ejemplares (`confirmar_ejemplares`, `agregar_relleno`)
    sigue funcionando igual."""


class EjemplarConfirmado(BaseModel):
    """Lo que el dueño confirmó de una lectura propuesta -- o una carta que
    agregó a mano, sin haber pasado por una tanda. `variant_id` es
    obligatorio: sin variante no hay precio de mercado con el que repartir
    (`allocation.py` rechaza explícitamente, nunca cae a un reparto en
    partes iguales encubierto), así que exigirlo acá es lo que le da
    sentido a esa regla más adelante."""

    card_id: str
    variant_id: str
    variant_label: str | None = None
    condition: str | None = None
    notes: str | None = None


class PurchaseService:
    def __init__(
        self,
        storage: StoragePort,
        catalog: Any,
        resolver: CardResolver | None,
        conn_factory: ConnFactory,
    ) -> None:
        self._storage = storage
        # `catalog`: espeja la carta antes de confirmarla (mismo motivo que
        # `CaptureService._asegurar_carta`) -- opcional para no obligar a
        # los tests que no tocan cartas a montarlo.
        self._catalog = catalog
        # `None` cuando `GEMINI_API` no está configurada -- `identificar_tanda`
        # lo distingue de "compra inexistente" con `GeminiNoConfigurado`.
        self._resolver = resolver
        self._conn_factory = conn_factory

    def crear(self, source_type: str, total_usd: Decimal, notes: str | None = None) -> Purchase:
        with self._conn_factory() as conn:
            return repository.crear_compra(conn, source_type, total_usd, notes=notes)

    def obtener(self, purchase_id: int) -> tuple[Purchase, list[EjemplarDeCompra]] | None:
        with self._conn_factory() as conn:
            compra = repository.obtener_compra(conn, purchase_id)
            if compra is None:
                return None
            ejemplares = repository.listar_ejemplares(conn, purchase_id)
        return compra, ejemplares

    async def identificar_tanda(
        self, purchase_id: int, foto: bytes, content_type: str
    ) -> ResolucionTanda | None:
        """`None` si la compra no existe. Lanza `GeminiNoConfigurado` si la
        identificación está apagada -- distinto de "compra inexistente"
        para que la ruta responda 503, no 404."""
        with self._conn_factory() as conn:
            compra = repository.obtener_compra(conn, purchase_id)
        if compra is None:
            return None
        if self._resolver is None:
            raise GeminiNoConfigurado()

        tanda = await self._resolver.resolver_varias(foto, content_type)

        # La foto vive en la compra, no en cada ejemplar (Task 4, Step 3):
        # una foto de doce cartas no es la foto de ninguna de ellas. Se sube
        # con un nombre propio por tanda (`tanda-<uuid>.jpg`) para no
        # destruir la evidencia de una tanda anterior en el bucket --
        # `purchase.photo_url` solo tiene una columna, así que recuerda
        # nomás el puntero a la última; las fotos de tandas previas siguen
        # vivas en el bucket bajo su propio path, aunque la compra ya no
        # apunte a ellas.
        path = f"purchases/{purchase_id}/tanda-{uuid4()}.jpg"
        await self._storage.upload(path, foto, content_type)
        with self._conn_factory() as conn:
            repository.guardar_foto(conn, purchase_id, path)

        return tanda

    async def _asegurar_carta(self, card_id: str, variant_id: str) -> None:
        """Espeja la carta (igual que `CaptureService._asegurar_carta`) y
        además comprueba que `variant_id` sea una de sus variantes reales --
        `_asegurar_carta` de captura no lo necesita porque ahí la variante
        llega en un PATCH aparte, pero acá `variant_id` es obligatorio desde
        el principio (sin él no hay precio de mercado con el que repartir),
        así que vale la pena decir cuál de las dos partes está mal en vez de
        dejar que la base lo rechace con una foránea genérica."""
        if self._catalog is None:
            return
        carta = await self._catalog.get_card(card_id)
        if carta is None:
            raise CartaDesconocida(card_id)
        if not any(v.id == variant_id for v in carta.variants):
            raise CartaDesconocida(f"{card_id} (variante «{variant_id}» no existe)")

    async def confirmar_ejemplares(
        self, purchase_id: int, ejemplares: list[EjemplarConfirmado]
    ) -> list[int] | None:
        """`tanda` propone; esto guarda -- nunca al revés (Task 4, Step 2).
        Cada carta se espeja antes de guardarla, igual que
        `CaptureService.registrar`, para que la compra recién confirmada
        tenga ya arte y precio sin una segunda vuelta."""
        with self._conn_factory() as conn:
            compra = repository.obtener_compra(conn, purchase_id)
        if compra is None:
            return None

        for ejemplar in ejemplares:
            await self._asegurar_carta(ejemplar.card_id, ejemplar.variant_id)

        with self._conn_factory() as conn:
            try:
                return repository.crear_ejemplares(
                    conn, purchase_id, [e.model_dump() for e in ejemplares]
                )
            except ForeignKeyViolation as exc:
                # Red de seguridad para cuando no hay `catalog` (algunos
                # tests): si el espejado no corrió, la base sigue
                # rechazando la variante inexistente.
                raise CartaDesconocida(
                    ejemplares[0].card_id if ejemplares else "desconocida"
                ) from exc

    def agregar_relleno(self, purchase_id: int, cantidad: int) -> list[int] | None:
        with self._conn_factory() as conn:
            compra = repository.obtener_compra(conn, purchase_id)
            if compra is None:
                return None
            return repository.crear_relleno(conn, purchase_id, cantidad)

    def repartir(
        self, purchase_id: int, method: str, costos_manuales: dict[int, Decimal] | None = None
    ) -> dict[int, Decimal] | None:
        """`None` si la compra no existe. Propaga `AllocationError` (y sus
        subclases) tal cual -- la ruta HTTP las traduce a 422 con el mensaje
        ya pensado para el dueño. No se guarda nada si `calcular_reparto`
        lanza: `guardar_reparto` corre después, nunca antes."""
        with self._conn_factory() as conn:
            compra = repository.obtener_compra(conn, purchase_id)
            if compra is None:
                return None
            ejemplares = repository.listar_ejemplares(conn, purchase_id)
            costos_manuales = costos_manuales or {}
            copias = [
                CopiaReparto(
                    id=e.id,
                    valor_mercado_usd=e.valor_mercado_usd,
                    es_bulk=e.is_bulk,
                    costo_manual_usd=costos_manuales.get(e.id),
                )
                for e in ejemplares
            ]
            asignaciones = calcular_reparto(compra.total_usd, copias, method)
            repository.guardar_reparto(conn, purchase_id, method, asignaciones)
        return asignaciones


__all__ = [
    "AllocationError",
    "EjemplarConfirmado",
    "GeminiNoConfigurado",
    "PurchaseService",
]
