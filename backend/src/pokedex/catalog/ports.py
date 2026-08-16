from typing import Protocol

from .models import Card, CardRef, SetRef


class CatalogPort(Protocol):
    """Fuente del catálogo de cartas. Intercambiable por diseño (spec §4.3)."""

    async def get_card(self, card_id: str) -> Card | None: ...

    async def find_by_set_and_number(self, set_id: str, local_id: str) -> Card | None: ...

    async def list_set_cards(self, set_id: str) -> list[CardRef]: ...

    async def list_sets(self) -> list[SetRef]: ...
