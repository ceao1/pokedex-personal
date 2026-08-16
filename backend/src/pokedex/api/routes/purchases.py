from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pokedex.api.routes.capture import RecognitionOut
from pokedex.api.routes.catalog import CardOut
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import TcgdexCatalog
from pokedex.collection.service import CartaDesconocida
from pokedex.collection.storage import SupabaseStorage
from pokedex.config import settings
from pokedex.purchases.allocation import AllocationError
from pokedex.purchases.models import EjemplarDeCompra, Purchase
from pokedex.purchases.service import EjemplarConfirmado, GeminiNoConfigurado, PurchaseService
from pokedex.recognition.gemini import GeminiRecognition
from pokedex.recognition.resolver import CardResolver, ResolucionTanda

router = APIRouter(prefix="/compras", tags=["compras"])


# --- DTOs de entrada --------------------------------------------------------


class PurchaseIn(BaseModel):
    source_type: str
    total_usd: Decimal
    notes: str | None = None


class EjemplaresIn(BaseModel):
    ejemplares: list[EjemplarConfirmado]


class RellenoIn(BaseModel):
    cantidad: int


class RepartirIn(BaseModel):
    method: str
    # Claves como `owned_copy.id`; solo se usa cuando `method == "manual"`.
    costos: dict[int, Decimal] | None = None


# --- DTOs de salida ----------------------------------------------------------


class PurchaseOut(BaseModel):
    id: int
    fecha: str
    source_type: str
    total_usd: float
    allocation_method: str
    photo_url: str | None
    notes: str | None

    @classmethod
    def from_purchase(cls, p: Purchase) -> "PurchaseOut":
        return cls(
            id=p.id,
            fecha=p.fecha.isoformat(),
            source_type=p.source_type,
            total_usd=float(p.total_usd),
            allocation_method=p.allocation_method,
            photo_url=p.photo_url,
            notes=p.notes,
        )


class LecturaTandaOut(BaseModel):
    reconocido: RecognitionOut
    carta: CardOut | None
    necesita_revision: bool
    motivo: str


class TandaOut(BaseModel):
    lecturas: list[LecturaTandaOut]
    # Cuántas encontró, para que la pantalla lo contraste contra lo que el
    # dueño dijo que había (spec del plan).
    total_encontradas: int
    excede_limite: bool

    @classmethod
    def from_resolucion(cls, tanda: ResolucionTanda) -> "TandaOut":
        return cls(
            lecturas=[
                LecturaTandaOut(
                    reconocido=RecognitionOut.from_recognition(lectura),
                    carta=CardOut.from_card(resolucion.card) if resolucion.card else None,
                    necesita_revision=resolucion.necesita_revision,
                    motivo=resolucion.motivo,
                )
                for lectura, resolucion in zip(tanda.lecturas, tanda.resoluciones, strict=True)
            ],
            total_encontradas=tanda.total_encontradas,
            excede_limite=tanda.excede_limite,
        )


class IdsOut(BaseModel):
    ids: list[int]


class EjemplarDeCompraOut(BaseModel):
    id: int
    card_id: str | None
    variant_id: str | None
    is_bulk: bool
    valor_mercado_usd: float | None
    costo_usd: float | None

    @classmethod
    def from_ejemplar(cls, e: EjemplarDeCompra) -> "EjemplarDeCompraOut":
        return cls(
            id=e.id,
            card_id=e.card_id,
            variant_id=e.variant_id,
            is_bulk=e.is_bulk,
            valor_mercado_usd=(
                float(e.valor_mercado_usd) if e.valor_mercado_usd is not None else None
            ),
            costo_usd=float(e.costo_usd) if e.costo_usd is not None else None,
        )


class PurchaseDetailOut(PurchaseOut):
    ejemplares: list[EjemplarDeCompraOut]


class AsignacionOut(BaseModel):
    ejemplar_id: int
    costo_usd: float


class RepartirOut(BaseModel):
    total_usd: float
    asignaciones: list[AsignacionOut]


# --- wiring ------------------------------------------------------------------


def get_service(request: Request) -> PurchaseService:
    """Mismo patrón que `capture.get_identification_service`: el
    `CardResolver` es `None` cuando `GEMINI_API` no está configurada, y
    `PurchaseService.identificar_tanda` lo distingue con `GeminiNoConfigurado`
    para que la ruta responda 503 -- el resto de la compra (crear, confirmar
    a mano, relleno, repartir) sigue funcionando igual sin la llave."""
    http_client = request.app.state.http_client
    storage = SupabaseStorage(
        settings.supabase_url,
        settings.supabase_secret_key,
        settings.storage_bucket,
        http_client,
        public_base_url=settings.storage_public_url or None,
    )
    catalog = CatalogService(
        TcgdexCatalog(settings.tcgdex_base_url, http_client), request.app.state.pool.connection
    )
    resolver = None
    if settings.gemini_api:
        recognition = GeminiRecognition(settings.gemini_api, settings.gemini_model, http_client)
        resolver = CardResolver(catalog, request.app.state.pool.connection, recognition=recognition)
    return PurchaseService(storage, catalog, resolver, request.app.state.pool.connection)


ServiceDep = Annotated[PurchaseService, Depends(get_service)]


def _no_encontrada(purchase_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"compra {purchase_id} no encontrada")


def _carta_desconocida_http(exc: CartaDesconocida) -> HTTPException:
    if exc.catalogo_inalcanzable:
        return HTTPException(
            status_code=503,
            detail=(
                f"No se pudo comprobar la carta {exc.card_id}: el catálogo no responde. "
                "No se guardó nada. Vuelve a intentarlo en un momento."
            ),
        )
    return HTTPException(
        status_code=422,
        detail=(
            f"La carta {exc.card_id} no existe en el catálogo. "
            "Revisa el set, el número de colección y la variante."
        ),
    )


def _allocation_error_http(exc: AllocationError) -> HTTPException:
    # El mensaje de cada subclase de `AllocationError` ya está pensado para
    # el dueño (ver `purchases/allocation.py`) -- se reenvía tal cual, en
    # vez de reescribirlo acá y arriesgarse a que las dos versiones diverjan.
    return HTTPException(status_code=422, detail=str(exc))


@router.post("", response_model=PurchaseOut)
def crear_compra(body: PurchaseIn, service: ServiceDep) -> PurchaseOut:
    compra = service.crear(body.source_type, body.total_usd, body.notes)
    return PurchaseOut.from_purchase(compra)


@router.get("/{purchase_id}", response_model=PurchaseDetailOut)
def obtener_compra(purchase_id: int, service: ServiceDep) -> PurchaseDetailOut:
    resultado = service.obtener(purchase_id)
    if resultado is None:
        raise _no_encontrada(purchase_id)
    compra, ejemplares = resultado
    return PurchaseDetailOut(
        **PurchaseOut.from_purchase(compra).model_dump(),
        ejemplares=[EjemplarDeCompraOut.from_ejemplar(e) for e in ejemplares],
    )


@router.post("/{purchase_id}/tanda", response_model=TandaOut)
async def tanda(purchase_id: int, request: Request, service: ServiceDep) -> TandaOut:
    """Identifica varias cartas en una foto y devuelve las lecturas
    resueltas -- **sin guardar nada**. `ejemplares` es quien guarda (Task 4,
    Step 2).

    La foto viaja como el cuerpo crudo del `POST` (`Content-Type:
    image/jpeg` o similar), no como `multipart/form-data`: este proyecto no
    trae `python-multipart` como dependencia, y agregarlo para un único
    endpoint no vale la complejidad de un tipo de cuerpo distinto al resto
    de la API."""
    datos = await request.body()
    content_type = request.headers.get("content-type") or "image/jpeg"
    try:
        resultado = await service.identificar_tanda(purchase_id, datos, content_type)
    except GeminiNoConfigurado:
        raise HTTPException(
            status_code=503,
            detail=(
                "La identificación por foto está apagada (falta configurar la llave de Gemini). "
                "Puedes registrar las cartas a mano."
            ),
        ) from None
    if resultado is None:
        raise _no_encontrada(purchase_id)
    return TandaOut.from_resolucion(resultado)


@router.post("/{purchase_id}/ejemplares", response_model=IdsOut)
async def ejemplares(purchase_id: int, body: EjemplaresIn, service: ServiceDep) -> IdsOut:
    try:
        ids = await service.confirmar_ejemplares(purchase_id, body.ejemplares)
    except CartaDesconocida as exc:
        raise _carta_desconocida_http(exc) from None
    if ids is None:
        raise _no_encontrada(purchase_id)
    return IdsOut(ids=ids)


@router.post("/{purchase_id}/relleno", response_model=IdsOut)
def relleno(purchase_id: int, body: RellenoIn, service: ServiceDep) -> IdsOut:
    if body.cantidad < 1:
        raise HTTPException(status_code=422, detail="la cantidad de relleno debe ser al menos 1")
    ids = service.agregar_relleno(purchase_id, body.cantidad)
    if ids is None:
        raise _no_encontrada(purchase_id)
    return IdsOut(ids=ids)


@router.post("/{purchase_id}/repartir", response_model=RepartirOut)
def repartir(purchase_id: int, body: RepartirIn, service: ServiceDep) -> RepartirOut:
    try:
        asignaciones = service.repartir(purchase_id, body.method, body.costos)
    except AllocationError as exc:
        raise _allocation_error_http(exc) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if asignaciones is None:
        raise _no_encontrada(purchase_id)

    resultado = service.obtener(purchase_id)
    assert resultado is not None  # ya se comprobó arriba que la compra existe
    compra, _ = resultado
    return RepartirOut(
        total_usd=float(compra.total_usd),
        asignaciones=[
            AsignacionOut(ejemplar_id=id_, costo_usd=float(costo))
            for id_, costo in asignaciones.items()
        ],
    )
