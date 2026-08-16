from decimal import Decimal

from pydantic import BaseModel, Field


class ExcelOption(BaseModel):
    """Una de las cuatro rutas de adquisición de una fila del Excel."""

    source_option: str
    raw_text: str
    reference_value_usd: Decimal | None = None


class ExcelRow(BaseModel):
    dex_number: int
    pokemon_name: str
    options: list[ExcelOption] = Field(default_factory=list)


class GalleryRow(BaseModel):
    dex_number: int
    pokemon_name: str
    raw_text: str
    reference_value_usd: Decimal | None = None
