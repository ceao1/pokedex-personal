from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pokedex.catalog.models import Card
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import TcgdexCatalog
from pokedex.config import settings

router = APIRouter(prefix="/catalog", tags=["catalog"])


class VariantOut(BaseModel):
    id: str
    type: str
    subtype: str | None
    stamp: list[str]
    foil: str | None
    price_usd: float | None
    price_captured_at: str | None


class CardOut(BaseModel):
    id: str
    name: str
    set_id: str
    set_name: str
    local_id: str
    set_card_count: int | None
    rarity: str | None
    image_url: str | None
    dex_number: int | None
    variants: list[VariantOut]

    @classmethod
    def from_card(cls, card: Card) -> "CardOut":
        return cls(
            **card.model_dump(exclude={"raw", "variants"}),
            variants=[
                VariantOut(
                    id=v.id,
                    type=v.type,
                    subtype=v.subtype,
                    stamp=v.stamp,
                    foil=v.foil,
                    price_usd=float(v.price_usd) if v.price_usd is not None else None,
                    price_captured_at=(
                        v.price_captured_at.isoformat() if v.price_captured_at else None
                    ),
                )
                for v in card.variants
            ],
        )


def get_service(request: Request) -> CatalogService:
    """El pool y el cliente HTTP viven en app.state, creados en el lifespan.

    Crear un httpx.AsyncClient por request lo dejaría sin cerrar y filtraría
    conexiones; crear el pool al importar impediría reabrirlo entre tests.
    """
    return CatalogService(
        TcgdexCatalog(settings.tcgdex_base_url, request.app.state.http_client),
        request.app.state.pool.connection,
    )


ServiceDep = Annotated[CatalogService, Depends(get_service)]


@router.get("/cards/{card_id}", response_model=CardOut)
async def get_card(card_id: str, service: ServiceDep) -> CardOut:
    card = await service.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"carta {card_id} no encontrada")
    return CardOut.from_card(card)


@router.get("/sets/{set_id}/{local_id}", response_model=CardOut)
async def get_card_by_number(set_id: str, local_id: str, service: ServiceDep) -> CardOut:
    card = await service.find_by_set_and_number(set_id, local_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"carta {set_id}-{local_id} no encontrada")
    return CardOut.from_card(card)
