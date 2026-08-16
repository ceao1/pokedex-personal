"""Orquesta el alta de un ejemplar: firma las dos subidas, crea el borrador
y expone el PATCH que lo va completando.

`client_draft_id` (generado en el celular) es la llave de idempotencia:
reenviar `iniciar_captura` con el mismo id no crea un segundo borrador
(`repository.crear_borrador` resuelve eso con `on conflict do nothing`), y
`registrar` es un PATCH parcial sobre esa misma fila.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from uuid import UUID

from psycopg import Connection
from pydantic import BaseModel

from . import repository
from .models import OwnedCopy, OwnedCopyIn
from .storage import StoragePort

ConnFactory = Callable[[], AbstractContextManager[Connection]]

# Vencimiento corto: el bucket es privado (decisión de diseño) y estas URLs
# solo necesitan vivir lo que tarda la pantalla que las pidió en cargar la
# imagen, no una sesión completa.
_DOWNLOAD_URL_SECONDS = 600


class CaptureUploads(BaseModel):
    front: str
    thumb: str


class CaptureStart(BaseModel):
    client_draft_id: UUID
    uploads: CaptureUploads


class CaptureService:
    def __init__(self, storage: StoragePort, conn_factory: ConnFactory) -> None:
        self._storage = storage
        self._conn_factory = conn_factory

    @staticmethod
    def _front_path(client_draft_id: UUID) -> str:
        return f"{client_draft_id}/front.jpg"

    @staticmethod
    def _thumb_path(client_draft_id: UUID) -> str:
        return f"{client_draft_id}/thumb.jpg"

    async def _con_urls_firmadas(self, copy: OwnedCopy | None) -> OwnedCopy | None:
        """Las fotos se guardan como *path* del bucket (ver repository); acá
        se cambian por una URL de descarga firmada de corta duración justo
        antes de cruzar al HTTP -- el bucket es privado a propósito, así que
        nunca se sirve el path crudo."""
        if copy is None:
            return None
        cambios = {}
        if copy.photo_front_url is not None:
            cambios["photo_front_url"] = await self._storage.signed_download_url(
                copy.photo_front_url, _DOWNLOAD_URL_SECONDS
            )
        if copy.photo_thumb_url is not None:
            cambios["photo_thumb_url"] = await self._storage.signed_download_url(
                copy.photo_thumb_url, _DOWNLOAD_URL_SECONDS
            )
        return copy.model_copy(update=cambios) if cambios else copy

    async def iniciar_captura(self, client_draft_id: UUID) -> CaptureStart:
        """Pide las dos URLs firmadas de subida y crea el borrador.

        Las rutas se derivan del `client_draft_id` en vez de generarse al
        azar: así, si el celular reintenta esta llamada *antes* de que la
        subida haya llegado a destino, pide de nuevo la firma para el mismo
        par de rutas en vez de dejar huérfano el primer intento.

        Ese razonamiento se rompe si el reintento llega *después* de que los
        bytes ya aterrizaron: verificado a mano contra Supabase Storage real,
        volver a pedir la firma para un path que ya tiene objeto devuelve
        {"statusCode":"409","error":"Duplicate"} con status HTTP 400, y
        `raise_for_status()` lo deja pasar como `httpx.HTTPStatusError` sin
        capturar -- el celular vería un 500. No se atrapa acá a propósito
        (atraparlo filtraría `httpx` a través del puerto); queda como riesgo
        conocido, documentado en el reporte del batch.
        """
        front = await self._storage.create_signed_upload(self._front_path(client_draft_id))
        thumb = await self._storage.create_signed_upload(self._thumb_path(client_draft_id))

        with self._conn_factory() as conn:
            repository.crear_borrador(conn, client_draft_id)

        return CaptureStart(
            client_draft_id=client_draft_id,
            uploads=CaptureUploads(front=front.signed_url, thumb=thumb.signed_url),
        )

    async def marcar_fotos_subidas(self, client_draft_id: UUID) -> OwnedCopy | None:
        """El celular ya subió los bytes directo al bucket; esto solo anota
        en qué paths quedaron, para no proxyar la imagen por el backend."""
        with self._conn_factory() as conn:
            repository.guardar_fotos(
                conn,
                client_draft_id,
                self._front_path(client_draft_id),
                self._thumb_path(client_draft_id),
            )
            copy = repository.obtener(conn, client_draft_id)
        return await self._con_urls_firmadas(copy)

    async def registrar(self, client_draft_id: UUID, datos: OwnedCopyIn) -> OwnedCopy | None:
        with self._conn_factory() as conn:
            copy = repository.actualizar(conn, client_draft_id, datos)
        return await self._con_urls_firmadas(copy)

    async def listar_pendientes(self) -> list[OwnedCopy]:
        with self._conn_factory() as conn:
            copies = repository.listar_pendientes(conn)
        return [await self._con_urls_firmadas(c) for c in copies]
