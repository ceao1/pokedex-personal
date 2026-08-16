from typing import Protocol

from .models import Recognition


class RecognitionPort(Protocol):
    """Fuente de identificación de cartas por foto. Intercambiable por
    diseño, igual que `CatalogPort` (spec §4.3)."""

    async def identify(self, image: bytes, mime_type: str) -> Recognition: ...
