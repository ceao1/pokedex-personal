from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CardVariant(BaseModel):
    id: str
    type: str
    subtype: str | None = None
    stamp: list[str] = Field(default_factory=list)
    foil: str | None = None
    size: str | None = None
    price_usd: Decimal | None = None
    price_captured_at: datetime | None = None
    raw: dict


class Card(BaseModel):
    id: str
    name: str
    set_id: str
    set_name: str
    local_id: str
    set_card_count: int | None = None
    rarity: str | None = None
    image_url: str | None = None
    dex_number: int | None = None
    raw: dict
    variants: list[CardVariant] = Field(default_factory=list)


class CardRef(BaseModel):
    """Referencia liviana a una carta, tal como la devuelve el listado de un set."""

    id: str
    local_id: str
    name: str
