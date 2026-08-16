from datetime import UTC, datetime

import httpx

from .models import Card, CardRef, SetRef
from .variants import parse_variants


def build_image_url(base: str | None, quality: str = "high", extension: str = "png") -> str | None:
    """TCGdex devuelve `image` como URL base sin extensión.

    Pedirla tal cual devuelve 404: hay que añadir `/{calidad}.{extensión}`.
    """
    if not base:
        return None
    return f"{base}/{quality}.{extension}"


def parse_card(payload: dict, captured_at: datetime) -> Card:
    card_set = payload.get("set") or {}
    dex_ids = payload.get("dexId") or []
    return Card(
        id=payload["id"],
        name=payload["name"],
        set_id=card_set.get("id", ""),
        set_name=card_set.get("name", ""),
        local_id=payload["localId"],
        set_card_count=(card_set.get("cardCount") or {}).get("official"),
        rarity=payload.get("rarity"),
        image_url=build_image_url(payload.get("image")),
        dex_number=dex_ids[0] if dex_ids else None,
        raw=payload,
        variants=parse_variants(payload, captured_at),
    )


class TcgdexCatalog:
    """Adaptador HTTP de la API pública de TCGdex."""

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def get_card(self, card_id: str) -> Card | None:
        return await self._fetch(f"{self._base_url}/cards/{card_id}")

    async def find_by_set_and_number(self, set_id: str, local_id: str) -> Card | None:
        return await self._fetch(f"{self._base_url}/sets/{set_id}/{local_id}")

    async def list_set_cards(self, set_id: str) -> list[CardRef]:
        """Listado liviano de un set. `GET /sets/{id}` trae `cards[]` con
        id, localId y name — suficiente para resolver por nombre."""
        response = await self._client.get(f"{self._base_url}/sets/{set_id}")
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return [
            CardRef(id=c["id"], local_id=c["localId"], name=c["name"])
            for c in response.json().get("cards", [])
        ]

    async def list_sets(self) -> list[SetRef]:
        """`GET /sets` trae los 218 sets con `{id, name, cardCount}` y
        nombres únicos (verificado): suficiente para mapear el `set_name`
        que devuelve el reconocimiento de foto a un id sin ambigüedad."""
        response = await self._client.get(f"{self._base_url}/sets")
        response.raise_for_status()
        return [
            SetRef(
                id=s["id"],
                name=s["name"],
                total=(s.get("cardCount") or {}).get("official"),
            )
            for s in response.json()
        ]

    async def _fetch(self, url: str) -> Card | None:
        response = await self._client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return parse_card(response.json(), datetime.now(UTC))
