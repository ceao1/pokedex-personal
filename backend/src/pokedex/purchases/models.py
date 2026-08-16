from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class Purchase(BaseModel):
    id: int
    fecha: date
    source_type: str
    total_usd: Decimal
    allocation_method: str
    photo_url: str | None
    notes: str | None
    created_at: datetime


class EjemplarDeCompra(BaseModel):
    """Un ejemplar tal como cuelga de una compra, con lo que hace falta para
    repartir (`valor_mercado_usd`, leído directo de `app.card_variant` -- la
    carta ya tuvo que espejarse al confirmarla, ver
    `PurchaseService.confirmar_ejemplares`) y para mostrarlo en la ficha de
    la compra (`costo_usd`, el mismo `app.owned_copy_costo` de siempre)."""

    id: int
    card_id: str | None
    variant_id: str | None
    is_bulk: bool
    valor_mercado_usd: Decimal | None
    costo_usd: Decimal | None
