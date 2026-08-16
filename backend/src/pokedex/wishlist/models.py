from decimal import Decimal

from pydantic import BaseModel


class WishlistItemIn(BaseModel):
    dex_number: int
    card_id: str | None = None
    variant_label: str | None = None
    raw_text: str
    source_option: str
    auto_resolved: bool = False
    is_favorite: bool = False
    reference_value_usd: Decimal | None = None
