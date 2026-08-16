"""Task 2: el reparto del costo de una compra entre sus ejemplares.

Función pura, sin base ni red (spec del plan): recibe el total pagado y la
lista de ejemplares con su precio de mercado, y devuelve cuánto le toca a
cada uno. El total nunca se modifica acá -- es inmutable por decisión de
diseño (`app.purchase.total_usd`); esta función solo decide cómo se reparte,
nunca cuánto se pagó.

Todo el cálculo pasa por centavos enteros (`int`), no por división de
`Decimal` con redondeo bancario: es la única forma de garantizar que la suma
de lo asignado sea **exactamente** el total, centavo a centavo, sin importar
cuántas cartas haya. El residuo de la división entera va siempre a la carta
de mayor valor de mercado -- nunca se reparte "a ojo" ni se pierde.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_CENTS = Decimal("0.01")

MARKET_VALUE = "market_value"
EQUAL = "equal"
MANUAL = "manual"
_METODOS = (MARKET_VALUE, EQUAL, MANUAL)


@dataclass(frozen=True)
class CopiaReparto:
    """Un ejemplar tal como lo ve el reparto: su identidad (lo que sea que
    el llamador use para reconocerlo después -- típicamente `owned_copy.id`),
    su precio de mercado si lo tiene, si está marcado bulk, y el costo que el
    dueño le haya escrito a mano (solo relevante para `manual`).

    El orden en que el llamador entrega la lista es el que decide, en caso
    de empate de valor de mercado, cuál absorbe el residuo del redondeo
    (`max()` se queda con la primera aparición del máximo) -- para que el
    mismo reparto no cambie de resultado entre una llamada y la siguiente,
    el llamador debe entregar siempre el mismo orden (ej. `order by id`).
    """

    id: Any
    valor_mercado_usd: Decimal | None = None
    es_bulk: bool = False
    costo_manual_usd: Decimal | None = None


class AllocationError(Exception):
    """Base de los errores de reparto. Ninguno de estos dejó nada a medio
    guardar: `repartir` o devuelve el reparto completo, o no devuelve nada."""


class FaltaPrecioDeMercado(AllocationError):
    """`market_value` no puede repartir sin precio: ni parcial (una carta sin
    precio) ni total (ninguna carta con precio). Nunca se cae a un reparto
    en partes iguales encubierto -- eso lo decide el dueño explícitamente
    eligiendo `equal`."""

    def __init__(self, ids_sin_precio: list[Any]) -> None:
        self.ids_sin_precio = list(ids_sin_precio)
        super().__init__(
            "no se puede repartir por valor de mercado: "
            f"{len(self.ids_sin_precio)} ejemplar(es) sin precio de mercado. "
            "Elige 'equal' o 'manual'."
        )


class NadieAbsorbeElCosto(AllocationError):
    """Todos los ejemplares elegibles están marcados bulk (o no hay
    ninguno): con un total mayor a cero, alguien tiene que absorberlo."""

    def __init__(self) -> None:
        super().__init__(
            "todos los ejemplares están marcados como bulk (o no hay ninguno): "
            "nadie absorbe el costo"
        )


class RepartoManualNoCuadra(AllocationError):
    """La suma de los costos manuales no coincide con el total. Lleva el
    residuo en vivo -- lo que falta (positivo) o sobra (negativo) -- para que
    la pantalla lo muestre sin que el dueño tenga que restar a mano."""

    def __init__(self, total_usd: Decimal, suma_usd: Decimal) -> None:
        self.total_usd = total_usd
        self.suma_usd = suma_usd
        self.residuo_usd = total_usd - suma_usd
        super().__init__(
            f"el reparto manual suma {suma_usd} y el total es {total_usd}: "
            f"residuo de {self.residuo_usd}"
        )


class CostoManualFaltante(AllocationError):
    """Un ejemplar elegible (no bulk) no trae `costo_manual_usd`: `manual`
    necesita que el dueño haya escrito un costo para cada uno, no solo para
    algunos."""

    def __init__(self, ids_faltantes: list[Any]) -> None:
        self.ids_faltantes = list(ids_faltantes)
        super().__init__(f"falta el costo manual de {len(self.ids_faltantes)} ejemplar(es)")


def _a_centavos(valor: Decimal) -> int:
    return int((valor * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _de_centavos(centavos: int) -> Decimal:
    return (Decimal(centavos) / 100).quantize(_CENTS)


def _id_de_mayor_valor(copias: list[CopiaReparto]) -> Any:
    """Empate lo rompe el orden de entrada: `max()` conserva la primera
    aparición del máximo, así que el llamador es quien fija el desempate
    entregando siempre el mismo orden (ver el docstring de `CopiaReparto`)."""
    return max(copias, key=lambda c: c.valor_mercado_usd or Decimal("-1")).id


def _repartir_por_valor(total_centavos: int, elegibles: list[CopiaReparto]) -> dict[Any, Decimal]:
    sin_precio = [c.id for c in elegibles if c.valor_mercado_usd is None]
    if sin_precio:
        raise FaltaPrecioDeMercado(sin_precio)

    valor_centavos = {c.id: _a_centavos(c.valor_mercado_usd) for c in elegibles}
    suma_valor = sum(valor_centavos.values())
    if suma_valor <= 0:
        # Todas con precio, pero ese precio es $0.00 en todas -- no hay
        # proporción posible (dividir por cero), y "todas sin precio" es
        # justo el caso que este método no puede disfrazar de reparto igual.
        raise FaltaPrecioDeMercado([c.id for c in elegibles])

    asignado: dict[Any, int] = {
        c.id: (valor_centavos[c.id] * total_centavos) // suma_valor for c in elegibles
    }
    residuo = total_centavos - sum(asignado.values())
    if residuo:
        asignado[_id_de_mayor_valor(elegibles)] += residuo
    return {id_: _de_centavos(v) for id_, v in asignado.items()}


def _repartir_partes_iguales(
    total_centavos: int, elegibles: list[CopiaReparto]
) -> dict[Any, Decimal]:
    n = len(elegibles)
    base = total_centavos // n
    residuo = total_centavos - base * n
    asignado: dict[Any, int] = {c.id: base for c in elegibles}
    if residuo:
        asignado[_id_de_mayor_valor(elegibles)] += residuo
    return {id_: _de_centavos(v) for id_, v in asignado.items()}


def _validar_manual(total_usd: Decimal, elegibles: list[CopiaReparto]) -> dict[Any, Decimal]:
    faltantes = [c.id for c in elegibles if c.costo_manual_usd is None]
    if faltantes:
        raise CostoManualFaltante(faltantes)

    asignado = {c.id: c.costo_manual_usd for c in elegibles}
    suma = sum(asignado.values())
    if suma != total_usd:
        raise RepartoManualNoCuadra(total_usd, suma)
    return asignado


def repartir(total_usd: Decimal, copias: list[CopiaReparto], method: str) -> dict[Any, Decimal]:
    """Reparte `total_usd` entre `copias` según `method`.

    Los ejemplares `es_bulk=True` siempre reciben `Decimal("0.00")` y quedan
    fuera del cálculo -- lo demás absorbe el total completo. Con
    `total_usd == 0` (un regalo) todo el mundo recibe cero sin más: ni
    siquiera hace falta que haya un elegible.
    """
    if method not in _METODOS:
        raise ValueError(f"método de reparto desconocido: {method!r}")
    if total_usd < 0:
        raise ValueError("el total no puede ser negativo")

    bulk = [c for c in copias if c.es_bulk]
    elegibles = [c for c in copias if not c.es_bulk]
    resultado: dict[Any, Decimal] = {c.id: Decimal("0.00") for c in bulk}

    if total_usd == 0:
        resultado.update({c.id: Decimal("0.00") for c in elegibles})
        return resultado

    if not elegibles:
        raise NadieAbsorbeElCosto()

    total_centavos = _a_centavos(total_usd)
    if method == MARKET_VALUE:
        resultado.update(_repartir_por_valor(total_centavos, elegibles))
    elif method == EQUAL:
        resultado.update(_repartir_partes_iguales(total_centavos, elegibles))
    else:
        resultado.update(_validar_manual(total_usd, elegibles))
    return resultado
