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

import httpx
from psycopg import Connection
from psycopg.errors import ForeignKeyViolation
from pydantic import BaseModel

from pokedex.recognition.models import Recognition
from pokedex.recognition.ports import RecognitionPort
from pokedex.recognition.resolver import CardResolver, ResolucionCarta

from . import repository
from .models import OwnedCopy, OwnedCopyIn
from .storage import AlreadyUploaded, StoragePort

ConnFactory = Callable[[], AbstractContextManager[Connection]]

# Vencimiento corto: el bucket es privado (decisión de diseño) y estas URLs
# solo necesitan vivir lo que tarda la pantalla que las pidió en cargar la
# imagen, no una sesión completa.
_DOWNLOAD_URL_SECONDS = 600


class CartaDesconocida(Exception):
    """El `card_id` que mandó el cliente no está en el catálogo.

    Distingue dos situaciones que no son la misma: la carta no existe, o no
    se pudo comprobar porque el catálogo no responde. La primera es culpa
    del dato y se arregla corrigiéndolo; la segunda es pasajera y se arregla
    reintentando. Confundirlas haría que el dueño corrigiera un set que
    estaba bien.

    Antes de existir, este caso salía como un 500 con la violación de clave
    foránea de Postgres en crudo.
    """

    def __init__(self, card_id: str, *, catalogo_inalcanzable: bool = False) -> None:
        self.card_id = card_id
        self.catalogo_inalcanzable = catalogo_inalcanzable
        super().__init__(card_id)


class CaptureUploads(BaseModel):
    front: str
    thumb: str


class CaptureStart(BaseModel):
    client_draft_id: UUID
    uploads: CaptureUploads


class CaptureService:
    def __init__(self, storage: StoragePort, conn_factory: ConnFactory, catalog=None) -> None:
        # `catalog` es opcional para no obligar a los tests a montarlo cuando
        # no tocan cartas. Cuando está, `registrar` espeja la carta antes de
        # guardarla, igual que hace el resto de la app: la primera vez que se
        # toca una carta, se copia.
        self._storage = storage
        self._conn_factory = conn_factory
        self._catalog = catalog

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

    async def _firmar_subida_o_ya_existente(self, path: str) -> str:
        """Pide la firma de subida; si Storage dice que el objeto ya existe
        (`AlreadyUploaded`), no es un error -- el celular ya lo subió en un
        intento anterior y esto es un reintento de `POST /captures` que
        perdió la respuesta. Se devuelve cadena vacía como señal de "ya
        subido, no hace falta volver a mandar la foto": el shape de la
        respuesta no cambia (`uploads.front`/`uploads.thumb` siguen siendo
        `str`), y un error genuino (auth, bucket inexistente, red caída)
        sigue propagándose sin capturar, porque `AlreadyUploaded` es el único
        caso que este `except` reconoce."""
        try:
            subida = await self._storage.create_signed_upload(path)
        except AlreadyUploaded:
            return ""
        return subida.signed_url

    async def iniciar_captura(self, client_draft_id: UUID) -> CaptureStart:
        """Pide las dos URLs firmadas de subida y crea el borrador.

        Las rutas se derivan del `client_draft_id` en vez de generarse al
        azar: así, si el celular reintenta esta llamada, pide de nuevo la
        firma para el mismo par de rutas en vez de dejar huérfano el primer
        intento -- y si el reintento llega después de que los bytes ya
        aterrizaron, `_firmar_subida_o_ya_existente` absorbe el 409 real de
        Storage en vez de dejarlo escapar como un 500.
        """
        front_url = await self._firmar_subida_o_ya_existente(self._front_path(client_draft_id))
        thumb_url = await self._firmar_subida_o_ya_existente(self._thumb_path(client_draft_id))

        with self._conn_factory() as conn:
            repository.crear_borrador(conn, client_draft_id)

        return CaptureStart(
            client_draft_id=client_draft_id,
            uploads=CaptureUploads(front=front_url, thumb=thumb_url),
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

    async def _asegurar_carta(self, card_id: str) -> None:
        """Espeja la carta si hace falta. `CatalogService.get_card` devuelve la
        copia local si ya está, así que esto no cuesta nada en el caso normal."""
        if self._catalog is None:
            return
        try:
            carta = await self._catalog.get_card(card_id)
        except httpx.HTTPError as exc:
            raise CartaDesconocida(card_id, catalogo_inalcanzable=True) from exc
        if carta is None:
            raise CartaDesconocida(card_id)

    async def registrar(self, client_draft_id: UUID, datos: OwnedCopyIn) -> OwnedCopy | None:
        if datos.card_id is not None:
            await self._asegurar_carta(datos.card_id)
        with self._conn_factory() as conn:
            try:
                copy = repository.actualizar(conn, client_draft_id, datos)
            except ForeignKeyViolation as exc:
                # Red de seguridad: si el espejado no corrió (catálogo no
                # inyectado) la base sigue rechazando la carta, y el cliente
                # merece el mismo mensaje claro y no un 500.
                raise CartaDesconocida(datos.card_id or "desconocida") from exc
        return await self._con_urls_firmadas(copy)

    async def listar_pendientes(self) -> list[OwnedCopy]:
        with self._conn_factory() as conn:
            copies = repository.listar_pendientes(conn)
        return [await self._con_urls_firmadas(c) for c in copies]


class FotoNoDisponible(Exception):
    """El ejemplar existe pero todavía no tiene foto frontal subida --
    distinto de que el ejemplar no exista (`None`, ver `identificar`)."""


class IdentificationResult(BaseModel):
    reconocido: Recognition
    resolucion: ResolucionCarta


class IdentificationService:
    """Orquesta `POST /captures/{id}/identificar`: baja la foto ya subida,
    la manda al `RecognitionPort` y valida la respuesta con `CardResolver`.

    A propósito **no escribe nada en `owned_copy`**: la decisión de aceptar
    la propuesta sigue siendo del humano (spec §5.2), y escribir acá sería
    exactamente lo que el spec prohíbe. El único efecto de lado que puede
    tener es el espejo del catálogo (`app.card`), que ya hace `CardResolver`
    a través de `CatalogService.get_card` -- lo mismo que `wishlist/seed.py`
    hace para cada carta por defecto del 151, para que el cliente reciba
    arte y precio.
    """

    def __init__(
        self,
        storage: StoragePort,
        recognition: RecognitionPort,
        resolver: CardResolver,
        conn_factory: ConnFactory,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._storage = storage
        self._recognition = recognition
        self._resolver = resolver
        self._conn_factory = conn_factory
        self._http_client = http_client

    async def identificar(self, client_draft_id: UUID) -> IdentificationResult | None:
        """`None` si el `client_draft_id` no tiene ejemplar (404 para el
        llamador). Lanza `FotoNoDisponible` si el ejemplar existe pero
        todavía no tiene foto frontal."""
        with self._conn_factory() as conn:
            copy = repository.obtener(conn, client_draft_id)
        if copy is None:
            return None
        if copy.photo_front_url is None:
            raise FotoNoDisponible(str(client_draft_id))

        signed_url = await self._storage.signed_download_url(
            copy.photo_front_url, _DOWNLOAD_URL_SECONDS
        )
        response = await self._http_client.get(signed_url)
        response.raise_for_status()
        image = response.content
        # No confiar en el content-type de Storage: una subida sin ese
        # header vuelve como `application/octet-stream` (o similar), y
        # Gemini lo rechaza o lo lee mal. El path es `front.jpg`, así que
        # `image/jpeg` es el fallback correcto.
        content_type = response.headers.get("content-type", "")
        mime_type = content_type if content_type.startswith("image/") else "image/jpeg"

        reconocido = await self._recognition.identify(image, mime_type)
        resolucion = await self._resolver.resolver(reconocido)
        return IdentificationResult(reconocido=reconocido, resolucion=resolucion)
