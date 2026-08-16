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
        # `GET /sets/{id}` es el mismo endpoint para dos necesidades
        # distintas: `list_set_cards` (las cartas) y `get_set_detail` (la
        # abreviatura). Cachear el payload crudo por set evita una segunda
        # llamada de red cuando ambos se piden para el mismo set en la vida
        # de esta instancia -- típicamente `CatalogService.set_por_codigo`
        # (construye el índice visitando el detalle de todos los sets) y
        # poco después el resolver, que pide `list_set_cards` del set que
        # matcheó por código.
        self._set_payload_cache: dict[str, dict] = {}

    async def get_card(self, card_id: str) -> Card | None:
        return await self._fetch(f"{self._base_url}/cards/{card_id}")

    async def find_by_set_and_number(self, set_id: str, local_id: str) -> Card | None:
        return await self._fetch(f"{self._base_url}/sets/{set_id}/{local_id}")

    async def _fetch_set_payload(self, set_id: str) -> dict | None:
        if set_id in self._set_payload_cache:
            return self._set_payload_cache[set_id]
        response = await self._client.get(f"{self._base_url}/sets/{set_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        self._set_payload_cache[set_id] = payload
        return payload

    async def list_set_cards(self, set_id: str) -> list[CardRef]:
        """Listado liviano de un set. `GET /sets/{id}` trae `cards[]` con
        id, localId y name — suficiente para resolver por nombre."""
        payload = await self._fetch_set_payload(set_id)
        if payload is None:
            return []
        return [
            CardRef(id=c["id"], local_id=c["localId"], name=c["name"])
            for c in payload.get("cards", [])
        ]

    async def list_sets(self) -> list[SetRef]:
        """`GET /sets` trae los 218 sets con `{id, name, cardCount}` y
        nombres únicos (verificado): suficiente para mapear el `set_name`
        que devuelve el reconocimiento de foto a un id sin ambigüedad.

        No trae `abbreviation` -- ver `get_set_detail`."""
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

    async def get_set_detail(self, set_id: str) -> SetRef | None:
        """`GET /sets/{id}` trae, además de `cards[]`, `abbreviation.official`
        -- el código impreso junto al número en la carta física (`ASC`,
        `BS`, `JU`). Verificado contra la API real: 188 de 218 sets lo
        tienen, y esas 188 abreviaturas son únicas -- un identificador
        perfecto cuando existe (ver `CatalogService.set_por_codigo`)."""
        payload = await self._fetch_set_payload(set_id)
        if payload is None:
            return None
        return SetRef(
            id=payload["id"],
            name=payload["name"],
            total=(payload.get("cardCount") or {}).get("official"),
            abbreviation=(payload.get("abbreviation") or {}).get("official"),
        )

    async def _fetch(self, url: str) -> Card | None:
        response = await self._client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return parse_card(response.json(), datetime.now(UTC))
