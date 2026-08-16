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
    # True cuando `dex_number` no vino de TCGdex (dexId ausente, como en las
    # cartas "Erika's X" de sets narrativos) sino que se infirió por
    # identificación de foto y se validó contra app.pokemon (ver
    # `recognition/resolver.py`). El catálogo nunca lo pisa: `repository.
    # set_inferred_dex_number` solo escribe si `dex_number` era null.
    dex_number_inferido: bool = False
    raw: dict
    variants: list[CardVariant] = Field(default_factory=list)


class CardRef(BaseModel):
    """Referencia liviana a una carta, tal como la devuelve el listado de un set."""

    id: str
    local_id: str
    name: str


class SetRef(BaseModel):
    """Referencia liviana a un set, tal como la devuelve `GET /sets`.

    `abbreviation` no viene en ese listado -- solo en el detalle de cada set
    (`GET /sets/{id}`, bajo `abbreviation.official`) -- así que nace `None`
    en la mayoría de las instancias y solo se completa cuando alguien pasó
    por `TcgdexCatalog.get_set_detail` (ver `CatalogService.set_por_codigo`).
    """

    id: str
    name: str
    total: int | None = None
    abbreviation: str | None = None
