from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class OwnedCopyIn(BaseModel):
    """Los campos que el celular puede mandar en un PATCH. Todos opcionales:
    el flujo los va completando en pantallas sucesivas."""

    card_id: str | None = None
    variant_id: str | None = None
    variant_label: str | None = None
    condition: str | None = None
    purchase_price_usd: Decimal | None = None
    source_type: str | None = None
    binder_id: int | None = None
    page: int | None = None
    capture_status: str | None = None
    lifecycle_status: str | None = None
    notes: str | None = None


class OwnedCopy(BaseModel):
    id: int
    client_draft_id: UUID
    card_id: str | None
    variant_id: str | None
    variant_label: str | None
    condition: str | None
    photo_front_url: str | None
    photo_thumb_url: str | None
    purchase_price_usd: Decimal | None
    source_type: str | None
    binder_id: int | None
    page: int | None
    capture_status: str
    lifecycle_status: str
    notes: str | None
    created_at: datetime
