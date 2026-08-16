from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from pokedex.wishlist import repository

router = APIRouter(tags=["pokedex"])


class PokemonOut(BaseModel):
    dex_number: int
    name: str
    wishlist_count: int
    sin_resolver: int
    # Ejemplares en posesión. Hoy siempre cero (ver el comentario del
    # repositorio); el contador del dashboard se alimenta de aquí y no de
    # `wishlist_count`, que cuenta rutas de caza y no cartas conseguidas.
    owned_count: int
    primary_image_url: str | None
    primary_card_name: str | None
    primary_price_usd: float | None


class WishlistItemOut(BaseModel):
    id: int
    dex_number: int | None
    card_id: str | None
    variant_label: str | None
    raw_text: str
    source_option: str
    auto_resolved: bool
    is_favorite: bool
    status: str
    reference_value_usd: float | None
    card_name: str | None
    image_url: str | None
    rarity: str | None
    set_name: str | None
    price_usd: float | None


class PokemonDetailOut(PokemonOut):
    options: list[WishlistItemOut]


def _to_float(row: dict) -> dict:
    """`numeric` de Postgres llega como Decimal y JSON no lo serializa.

    La conversión a float ocurre solo en el borde HTTP, nunca en el modelo ni
    en la base: el dinero se guarda y se calcula en Decimal.
    """
    salida = dict(row)
    for campo in ("reference_value_usd", "price_usd", "primary_price_usd"):
        if salida.get(campo) is not None:
            salida[campo] = float(salida[campo])
    salida.pop("price_captured_at", None)
    return salida


@router.get("/pokedex", response_model=list[PokemonOut])
def list_pokedex(request: Request) -> list[PokemonOut]:
    with request.app.state.pool.connection() as conn:
        return [PokemonOut(**_to_float(row)) for row in repository.list_pokedex(conn)]


@router.get("/pokedex/{dex_number}", response_model=PokemonDetailOut)
def get_pokemon(dex_number: int, request: Request) -> PokemonDetailOut:
    with request.app.state.pool.connection() as conn:
        fila = next(
            (r for r in repository.list_pokedex(conn) if r["dex_number"] == dex_number), None
        )
        if fila is None:
            raise HTTPException(status_code=404, detail=f"dex {dex_number} no encontrado")
        opciones = repository.list_wishlist(conn, dex_number)
    return PokemonDetailOut(
        **_to_float(fila), options=[WishlistItemOut(**_to_float(o)) for o in opciones]
    )


@router.get("/wishlist", response_model=list[WishlistItemOut])
def list_wishlist(request: Request) -> list[WishlistItemOut]:
    with request.app.state.pool.connection() as conn:
        return [WishlistItemOut(**_to_float(row)) for row in repository.list_wishlist(conn)]
