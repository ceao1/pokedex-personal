import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pokedex.collection import repository as collection_repository
from pokedex.collection.storage import StoragePort, SupabaseStorage
from pokedex.config import settings
from pokedex.wishlist import repository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pokedex"])

# Vencimiento corto, igual que en `CaptureService`: estas URLs solo necesitan
# vivir lo que tarda la ficha en cargar las imágenes, no una sesión completa.
_DOWNLOAD_URL_SECONDS = 600


class PokemonOut(BaseModel):
    dex_number: int
    name: str
    wishlist_count: int
    sin_resolver: int
    # Ejemplares en posesión, excluyendo los vendidos. El contador del
    # dashboard se alimenta de aquí y no de `wishlist_count`, que cuenta
    # rutas de caza y no cartas conseguidas.
    owned_count: int
    primary_image_url: str | None
    primary_card_name: str | None
    primary_price_usd: float | None
    # Spec §11/§15: todo precio de mercado se muestra con la fecha en que se
    # congeló (D5: nunca se refresca), para que la vista pueda avisar de la
    # antigüedad en vez de mostrar un número sin sostén.
    primary_price_captured_at: str | None


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
    # Ídem primary_price_captured_at en PokemonOut: la fecha del precio
    # congelado de esta opción puntual.
    price_captured_at: str | None


class OwnedCopyOut(BaseModel):
    id: int
    card_id: str | None
    card_name: str | None
    set_name: str | None
    local_id: str | None
    variant_label: str | None
    condition: str | None
    purchase_price_usd: float | None
    # El bucket es privado: esto es una URL firmada de corta duración, nunca
    # el path crudo que guarda el repositorio. `None` si no hay foto, o si
    # firmarla falló -- la foto es un adorno de esta pantalla, los datos no.
    photo_url: str | None
    notes: str | None
    created_at: datetime


class PokemonDetailOut(PokemonOut):
    options: list[WishlistItemOut]
    copies: list[OwnedCopyOut]


def _to_float(row: dict) -> dict:
    """`numeric` de Postgres llega como Decimal y JSON no lo serializa.

    La conversión a float ocurre solo en el borde HTTP, nunca en el modelo ni
    en la base: el dinero se guarda y se calcula en Decimal.
    """
    salida = dict(row)
    for campo in ("reference_value_usd", "price_usd", "primary_price_usd", "purchase_price_usd"):
        if salida.get(campo) is not None:
            salida[campo] = float(salida[campo])
    # Spec §11/§15: la fecha del precio congelado se expone, no se descarta.
    # Serializada a ISO 8601 porque los DTO la declaran `str`, igual que el
    # resto de la API.
    for campo in ("price_captured_at", "primary_price_captured_at"):
        if salida.get(campo) is not None:
            salida[campo] = salida[campo].isoformat()
    return salida


def get_storage(request: Request) -> StoragePort:
    """Mismo constructor que usa `routes/capture.py`: `public_base_url`
    importa aquí también, porque estas URLs las abre el mismo celular que
    subió la foto, no el servidor."""
    return SupabaseStorage(
        settings.supabase_url,
        settings.supabase_secret_key,
        settings.storage_bucket,
        request.app.state.http_client,
        public_base_url=settings.storage_public_url or None,
    )


StorageDep = Annotated[StoragePort, Depends(get_storage)]


async def _firmar_fotos(storage: StoragePort, ejemplares: list[dict]) -> dict[str, str | None]:
    """Firma en lote las fotos de todos los ejemplares de una ficha, no una
    petición por ejemplar dentro de un bucle sin control. Si firmar falla
    (red caída, Storage abajo), ningún ejemplar revienta la ficha entera: se
    devuelven todos con `photo_url: None`, porque la foto es decoración y los
    datos no."""
    paths = [e["photo_front_url"] for e in ejemplares if e["photo_front_url"]]
    if not paths:
        return {}
    try:
        return await storage.signed_download_urls(paths, _DOWNLOAD_URL_SECONDS)
    except Exception:
        # No se propaga: la foto es decoración de esta pantalla, los datos
        # no. Pero un fallo silencioso de Storage es justo lo que este
        # proyecto ya sufrió una vez (subida que "funcionaba" con cero bytes
        # en el bucket), así que queda logueado para no repetir esa historia.
        logger.exception("no se pudieron firmar %d foto(s) para la ficha", len(paths))
        return dict.fromkeys(paths)


@router.get("/pokedex", response_model=list[PokemonOut])
def list_pokedex(request: Request) -> list[PokemonOut]:
    with request.app.state.pool.connection() as conn:
        return [PokemonOut(**_to_float(row)) for row in repository.list_pokedex(conn)]


@router.get("/pokedex/{dex_number}", response_model=PokemonDetailOut)
async def get_pokemon(dex_number: int, request: Request, storage: StorageDep) -> PokemonDetailOut:
    with request.app.state.pool.connection() as conn:
        fila = next(
            (r for r in repository.list_pokedex(conn) if r["dex_number"] == dex_number), None
        )
        if fila is None:
            raise HTTPException(status_code=404, detail=f"dex {dex_number} no encontrado")
        opciones = repository.list_wishlist(conn, dex_number)
        ejemplares = collection_repository.listar_por_dex(conn, dex_number)

    fotos = await _firmar_fotos(storage, ejemplares)
    copies = [
        OwnedCopyOut(**_to_float(e), photo_url=fotos.get(e["photo_front_url"])) for e in ejemplares
    ]

    return PokemonDetailOut(
        **_to_float(fila),
        options=[WishlistItemOut(**_to_float(o)) for o in opciones],
        copies=copies,
    )


@router.get("/wishlist", response_model=list[WishlistItemOut])
def list_wishlist(request: Request) -> list[WishlistItemOut]:
    with request.app.state.pool.connection() as conn:
        return [WishlistItemOut(**_to_float(row)) for row in repository.list_wishlist(conn)]
