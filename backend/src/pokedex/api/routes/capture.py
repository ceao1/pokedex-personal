from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pokedex.collection.models import OwnedCopy, OwnedCopyIn
from pokedex.collection.service import CaptureService
from pokedex.collection.storage import SupabaseStorage
from pokedex.config import settings

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
    )
    return CaptureService(storage, request.app.state.pool.connection)


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
    copy = await service.registrar(client_draft_id, datos)
    if copy is None:
        raise _no_encontrado(client_draft_id)
    return OwnedCopyOut.from_copy(copy)


@router.get("/pendientes", response_model=list[OwnedCopyOut])
async def list_pendientes(service: ServiceDep) -> list[OwnedCopyOut]:
    return [OwnedCopyOut.from_copy(c) for c in await service.listar_pendientes()]
