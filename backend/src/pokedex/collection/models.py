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
    # El casillero del 151 al que cuelga este ejemplar cuando su carta
    # exacta (set y número) no se conoce todavía, o nunca se conoce (spec de
    # la task: "permite que el set quede vacío, si es posible identificarlo
    # bien"). La carta manda cuando existe -- ver `coalesce(card.dex_number,
    # owned_copy.dex_number)` en `collection/repository.py` y
    # `wishlist/repository.py`.
    dex_number: int | None = None


class OwnedCopy(BaseModel):
    id: int
    client_draft_id: UUID
    card_id: str | None
    variant_id: str | None
    variant_label: str | None
    condition: str | None
    photo_front_url: str | None
    photo_thumb_url: str | None
    # El precio suelto histórico -- lo que un ejemplar sin compra sigue
    # usando. Nunca se lee directo para "cuánto costó esto": esa pregunta la
    # responde `app.owned_copy_costo` (`coalesce(assigned_cost_usd,
    # purchase_price_usd)`, ver la migración de `app.purchase`), el único
    # sitio donde se decide -- `listar_por_dex`/`listar_fuera_del_151`, en
    # este mismo módulo, lo exponen ya resuelto bajo `purchase_price_usd`
    # para las vistas de lectura. Este campo sigue siendo el valor crudo de
    # la columna porque `OwnedCopyIn`/PATCH escriben ahí directo, y mezclar
    # lectura resuelta con escritura cruda en el mismo nombre sería la
    # mentira que la task de compras vino a evitar.
    purchase_price_usd: Decimal | None
    source_type: str | None
    binder_id: int | None
    page: int | None
    capture_status: str
    lifecycle_status: str
    notes: str | None
    dex_number: int | None
    # La compra de la que cuelga este ejemplar, si la hay -- `None` para todo
    # lo capturado antes de la task de compras, o para lo capturado a mano
    # fuera de una.
    purchase_id: int | None
    # Lo que esa compra le asignó a este ejemplar puntual al repartir su
    # costo (`purchases/allocation.py`). `None` hasta que se reparte, o
    # siempre `None` si el ejemplar no cuelga de una compra.
    assigned_cost_usd: Decimal | None
    # Relleno de bulk: sin carta, sin foto, a costo cero (ver
    # `purchases/repository.py`). Excluido a propósito del reparto.
    is_bulk: bool
    created_at: datetime
