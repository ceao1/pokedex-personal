from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pokedex.api.routes.catalog import CardOut
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import TcgdexCatalog
from pokedex.collection.models import OwnedCopy, OwnedCopyIn
from pokedex.collection.service import (
    CaptureService,
    CartaDesconocida,
    FotoNoDisponible,
    IdentificationService,
)
from pokedex.collection.storage import SupabaseStorage
from pokedex.config import settings
from pokedex.recognition.gemini import GeminiRecognition
from pokedex.recognition.models import Recognition
from pokedex.recognition.resolver import CardResolver

router = APIRouter(prefix="/captures", tags=["captures"])


class StartCaptureIn(BaseModel):
    client_draft_id: UUID


class UploadsOut(BaseModel):
    front: str
    thumb: str


class StartCaptureOut(BaseModel):
    client_draft_id: UUID
    uploads: UploadsOut


class OwnedCopyOut(BaseModel):
    id: int
    client_draft_id: UUID
    card_id: str | None
    variant_id: str | None
    variant_label: str | None
    condition: str | None
    photo_front_url: str | None
    photo_thumb_url: str | None
    purchase_price_usd: float | None
    source_type: str | None
    binder_id: int | None
    page: int | None
    capture_status: str
    lifecycle_status: str
    notes: str | None

    @classmethod
    def from_copy(cls, copy: OwnedCopy) -> "OwnedCopyOut":
        return cls(
            **copy.model_dump(exclude={"purchase_price_usd", "created_at"}),
            # `numeric` llega como Decimal; el cruce a float pasa acá, en el
            # borde HTTP, nunca antes (constraint global: Decimal en Python,
            # float solo al servir JSON).
            purchase_price_usd=(
                float(copy.purchase_price_usd) if copy.purchase_price_usd is not None else None
            ),
        )


def get_service(request: Request) -> CaptureService:
    """El pool y el cliente HTTP viven en app.state, creados en el lifespan
    (ver `catalog.get_service`, mismo motivo: no crear un cliente por
    request ni el pool al importar)."""
    storage = SupabaseStorage(
        settings.supabase_url,
        settings.supabase_secret_key,
        settings.storage_bucket,
        request.app.state.http_client,
        public_base_url=settings.storage_public_url or None,
    )
    catalog = CatalogService(
        TcgdexCatalog(settings.tcgdex_base_url, request.app.state.http_client),
        request.app.state.pool.connection,
    )
    return CaptureService(storage, request.app.state.pool.connection, catalog)


ServiceDep = Annotated[CaptureService, Depends(get_service)]


def _no_encontrado(client_draft_id: UUID) -> HTTPException:
    return HTTPException(status_code=404, detail=f"ejemplar {client_draft_id} no encontrado")


@router.post("", response_model=StartCaptureOut)
async def start_capture(body: StartCaptureIn, service: ServiceDep) -> StartCaptureOut:
    """`client_draft_id` lo genera el celular; reenviar el mismo id no crea
    un segundo ejemplar (ver `repository.crear_borrador`)."""
    inicio = await service.iniciar_captura(body.client_draft_id)
    return StartCaptureOut(
        client_draft_id=inicio.client_draft_id,
        uploads=UploadsOut(front=inicio.uploads.front, thumb=inicio.uploads.thumb),
    )


@router.post("/{client_draft_id}/photo-uploaded", response_model=OwnedCopyOut)
async def photo_uploaded(client_draft_id: UUID, service: ServiceDep) -> OwnedCopyOut:
    copy = await service.marcar_fotos_subidas(client_draft_id)
    if copy is None:
        raise _no_encontrado(client_draft_id)
    return OwnedCopyOut.from_copy(copy)


@router.patch("/{client_draft_id}", response_model=OwnedCopyOut)
async def update_capture(
    client_draft_id: UUID, datos: OwnedCopyIn, service: ServiceDep
) -> OwnedCopyOut:
    """PATCH parcial: los campos que el celular no manda quedan como estaban.
    Un PATCH vacío (retry de un celular sin cambios) no debe reventar."""
    try:
        copy = await service.registrar(client_draft_id, datos)
    except CartaDesconocida as exc:
        if exc.catalogo_inalcanzable:
            # 503 y no 422: el dato del cliente puede estar perfecto, solo que
            # no se pudo comprobar. Decirle que corrija algo correcto sería
            # peor que pedirle que reintente.
            raise HTTPException(
                status_code=503,
                detail=(
                    f"No se pudo comprobar la carta {exc.card_id}: el catálogo no responde. "
                    "No se guardó nada. Vuelve a intentarlo en un momento."
                ),
            ) from None
        raise HTTPException(
            status_code=422,
            detail=(
                f"La carta {exc.card_id} no existe en el catálogo. "
                "Revisa el set y el número de colección."
            ),
        ) from None
    if copy is None:
        raise _no_encontrado(client_draft_id)
    return OwnedCopyOut.from_copy(copy)


@router.get("/pendientes", response_model=list[OwnedCopyOut])
async def list_pendientes(service: ServiceDep) -> list[OwnedCopyOut]:
    return [OwnedCopyOut.from_copy(c) for c in await service.listar_pendientes()]


class RecognitionOut(BaseModel):
    name: str | None
    set_name: str | None
    number: str | None
    rarity: str | None
    species: str | None
    dex_number: int | None
    confidence: float
    needs_review: bool

    @classmethod
    def from_recognition(cls, reconocido: Recognition) -> "RecognitionOut":
        # `raw` nunca cruza al HTTP: es para depurar, no para el cliente.
        return cls(**reconocido.model_dump(exclude={"raw"}))


class IdentificarOut(BaseModel):
    reconocido: RecognitionOut
    carta: CardOut | None
    necesita_revision: bool
    motivo: str


def get_identification_service(request: Request) -> IdentificationService | None:
    """`None` cuando `GEMINI_API` no está configurada -- el handler responde
    503 en ese caso y nada más se rompe: el registro a mano sigue exactamente
    igual. La llave se revisa acá, antes de construir nada, para no gastar
    ninguna llamada (ni siquiera a Storage) cuando la identificación está
    apagada."""
    if not settings.gemini_api:
        return None
    http_client = request.app.state.http_client
    storage = SupabaseStorage(
        settings.supabase_url,
        settings.supabase_secret_key,
        settings.storage_bucket,
        http_client,
        public_base_url=settings.storage_public_url or None,
    )
    recognition = GeminiRecognition(settings.gemini_api, settings.gemini_model, http_client)
    catalog = CatalogService(
        TcgdexCatalog(settings.tcgdex_base_url, http_client), request.app.state.pool.connection
    )
    # `recognition`/`http_client`: el desempate por imagen (task 3) los
    # necesita para bajar el arte de cada candidata y preguntarle a Gemini
    # cuál coincide con la foto -- solo se invoca con 2 a 5 candidatas
    # confirmadas por el catálogo (ver `CardResolver._intentar_desempate`).
    resolver = CardResolver(
        catalog,
        request.app.state.pool.connection,
        recognition=recognition,
        http_client=http_client,
    )
    return IdentificationService(
        storage, recognition, resolver, request.app.state.pool.connection, http_client
    )


IdentificationDep = Annotated[IdentificationService | None, Depends(get_identification_service)]


@router.post("/{client_draft_id}/identificar", response_model=IdentificarOut)
async def identificar(client_draft_id: UUID, service: IdentificationDep) -> IdentificarOut:
    """No escribe nada en `owned_copy`: propone, el humano dispone (spec
    §5.2). Si la resolución tiene éxito, la carta ya quedó espejada en
    `app.card` -- lo hace `CardResolver` a través de `CatalogService`, igual
    que `_asegurar_espejo` en el import del Excel -- así que el cliente
    recibe arte y precio sin una segunda vuelta."""
    if service is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "La identificación por foto está apagada (falta configurar la llave de Gemini). "
                "Puedes registrar la carta a mano."
            ),
        )
    try:
        resultado = await service.identificar(client_draft_id)
    except FotoNoDisponible:
        raise HTTPException(
            status_code=409, detail="el ejemplar todavía no tiene foto subida"
        ) from None
    if resultado is None:
        raise _no_encontrado(client_draft_id)
    return IdentificarOut(
        reconocido=RecognitionOut.from_recognition(resultado.reconocido),
        carta=(
            CardOut.from_card(resultado.resolucion.card)
            if resultado.resolucion.card is not None
            else None
        ),
        necesita_revision=resultado.resolucion.necesita_revision,
        motivo=resultado.resolucion.motivo,
    )
