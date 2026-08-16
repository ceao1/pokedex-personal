from typing import Protocol

from pydantic import BaseModel

from .models import Recognition


class CandidataImagen(BaseModel):
    """Una carta candidata del catálogo, con su imagen de referencia, para
    el desempate por foto (`RecognitionPort.elegir_entre`). `image` es el
    arte oficial de la carta (bytes ya descargados de `Card.image_url`),
    nunca la foto del dueño -- esa es el primer parámetro de `elegir_entre`."""

    card_id: str
    image: bytes


class RecognitionPort(Protocol):
    """Fuente de identificación de cartas por foto. Intercambiable por
    diseño, igual que `CatalogPort` (spec §4.3)."""

    async def identify(self, image: bytes, mime_type: str) -> Recognition: ...

    async def elegir_entre(self, foto: bytes, candidatas: list[CandidataImagen]) -> str | None:
        """Solo se invoca con 2 a 5 candidatas confirmadas por el catálogo
        (ver `recognition/resolver.py`) que no se distinguen por nombre ni
        dexId -- nunca como primer paso. Devuelve el `card_id` elegido, o
        `None` si ninguna coincide con certeza: se le pide al modelo que
        prefiera `None` a adivinar, porque un desempate equivocado no lo
        revisaría nadie."""
        ...
