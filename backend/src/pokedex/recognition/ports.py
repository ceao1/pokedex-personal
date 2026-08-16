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

    async def identificar_varias(self, foto: bytes, mime_type: str) -> list[Recognition]:
        """Task 3 (compras por tanda): una foto compuesta con varias cartas
        físicas extendidas una junto a otra. Devuelve una `Recognition` por
        carta que el modelo dice haber visto, en el mismo orden en que las
        leyó -- nunca inventa una carta que no está en la foto, y nunca
        saltea una que sí está aunque no la pueda leer con certeza (en ese
        caso, el elemento vuelve igual, con los campos dudosos en `None` y
        `needs_review=True`; ver `CardResolver.resolver_varias`, que resuelve
        cada elemento por separado con las mismas reglas de `resolver()`).

        No recorta a un máximo: doce cartas por tanda es el límite medido sin
        error (ver el plan), pero es una recomendación para el humano, no un
        tope que este método haga cumplir -- quien decide si avisar por
        exceso es el llamador (`CardResolver.resolver_varias`)."""
        ...

    async def elegir_entre(self, foto: bytes, candidatas: list[CandidataImagen]) -> str | None:
        """Solo se invoca con 2 a 5 candidatas confirmadas por el catálogo
        (ver `recognition/resolver.py`) que no se distinguen por nombre ni
        dexId -- nunca como primer paso. Devuelve el `card_id` elegido, o
        `None` si ninguna coincide con certeza: se le pide al modelo que
        prefiera `None` a adivinar, porque un desempate equivocado no lo
        revisaría nadie."""
        ...
