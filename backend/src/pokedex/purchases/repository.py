"""Persistencia de las compras y sus ejemplares. SQL plano, sin ORM -- mismo
estilo que `collection/repository.py`.
"""

from decimal import Decimal
from typing import Any

from psycopg import Connection

from .models import EjemplarDeCompra, Purchase

_COLUMNS = "id, fecha, source_type, total_usd, allocation_method, photo_url, notes, created_at"

_INSERT_COMPRA = f"""
insert into app.purchase (source_type, total_usd, allocation_method, notes)
values (%(source_type)s, %(total_usd)s, %(allocation_method)s, %(notes)s)
returning {_COLUMNS}
"""

_SELECT_COMPRA = f"select {_COLUMNS} from app.purchase where id = %(id)s"

_UPDATE_FOTO = """
update app.purchase set photo_url = %(photo_url)s where id = %(id)s
"""

_UPDATE_METODO = """
update app.purchase set allocation_method = %(method)s where id = %(id)s
"""

# `gen_random_uuid()`: todo `owned_copy` exige `client_draft_id` (`not null
# unique`) aunque nunca haya pasado por el flujo de captura de una sola
# carta -- acá no hay celular que lo genere, así que lo genera Postgres.
# `capture_status = 'listo'`: un ejemplar confirmado desde una compra no es
# un borrador a medio llenar (spec de `GET /captures/pendientes`); sin esto
# quedaría viviendo ahí para siempre.
_INSERT_EJEMPLAR = """
insert into app.owned_copy (
    client_draft_id, purchase_id, card_id, variant_id, variant_label,
    condition, dex_number, notes, capture_status
)
values (
    gen_random_uuid(), %(purchase_id)s, %(card_id)s, %(variant_id)s, %(variant_label)s,
    %(condition)s, %(dex_number)s, %(notes)s, 'listo'
)
returning id
"""

_INSERT_RELLENO = """
insert into app.owned_copy (client_draft_id, purchase_id, is_bulk, capture_status)
values (gen_random_uuid(), %(purchase_id)s, true, 'listo')
returning id
"""

# El precio de mercado se lee directo de `app.card_variant`, no del
# catálogo remoto: para cuando se reparte, la carta ya tuvo que espejarse al
# confirmarla (`PurchaseService.confirmar_ejemplares`), así que el precio ya
# vive local. El join es por la pareja completa `(card_id, variant_id)` --
# la clave primaria real de `card_variant` -- nunca por `card_id` a solas:
# eso multiplicaría cada ejemplar por sus variantes y descuadraría el
# reparto (el bug de fan-out que ya apareció dos veces en este proyecto).
# `order by id` fija el orden en el que `PurchaseService.repartir` entrega
# los ejemplares a `allocation.repartir`: el desempate del residuo de
# redondeo depende de ese orden, y tiene que ser el mismo en cada llamada
# para que recalcular con otro método no cambie la carta que absorbe el
# residuo sin motivo.
_LISTAR_EJEMPLARES = """
select o.id, o.card_id, o.variant_id, o.is_bulk,
       v.price_usd as valor_mercado_usd,
       app.owned_copy_costo(o) as costo_usd
from app.owned_copy o
left join app.card_variant v on v.card_id = o.card_id and v.id = o.variant_id
where o.purchase_id = %(purchase_id)s
order by o.id
"""

_UPDATE_COSTO_ASIGNADO = """
update app.owned_copy set assigned_cost_usd = %(costo)s, updated_at = now()
where id = %(id)s and purchase_id = %(purchase_id)s
"""


def crear_compra(
    conn: Connection,
    source_type: str,
    total_usd: Decimal,
    allocation_method: str = "market_value",
    notes: str | None = None,
) -> Purchase:
    row = conn.execute(
        _INSERT_COMPRA,
        {
            "source_type": source_type,
            "total_usd": total_usd,
            "allocation_method": allocation_method,
            "notes": notes,
        },
    ).fetchone()
    return Purchase(**row)


def obtener_compra(conn: Connection, purchase_id: int) -> Purchase | None:
    row = conn.execute(_SELECT_COMPRA, {"id": purchase_id}).fetchone()
    return Purchase(**row) if row is not None else None


def guardar_foto(conn: Connection, purchase_id: int, photo_path: str) -> None:
    conn.execute(_UPDATE_FOTO, {"id": purchase_id, "photo_url": photo_path})


def guardar_metodo(conn: Connection, purchase_id: int, method: str) -> None:
    conn.execute(_UPDATE_METODO, {"id": purchase_id, "method": method})


def crear_ejemplares(
    conn: Connection, purchase_id: int, ejemplares: list[dict[str, Any]]
) -> list[int]:
    """Cada elemento de `ejemplares` trae `card_id`, `variant_id` y,
    opcionalmente, `variant_label`, `condition`, `dex_number`, `notes`."""
    ids = []
    for ejemplar in ejemplares:
        row = conn.execute(
            _INSERT_EJEMPLAR,
            {
                "purchase_id": purchase_id,
                "card_id": ejemplar["card_id"],
                "variant_id": ejemplar["variant_id"],
                "variant_label": ejemplar.get("variant_label"),
                "condition": ejemplar.get("condition"),
                "dex_number": ejemplar.get("dex_number"),
                "notes": ejemplar.get("notes"),
            },
        ).fetchone()
        ids.append(row["id"])
    return ids


def crear_relleno(conn: Connection, purchase_id: int, cantidad: int) -> list[int]:
    ids = []
    for _ in range(cantidad):
        row = conn.execute(_INSERT_RELLENO, {"purchase_id": purchase_id}).fetchone()
        ids.append(row["id"])
    return ids


def listar_ejemplares(conn: Connection, purchase_id: int) -> list[EjemplarDeCompra]:
    rows = conn.execute(_LISTAR_EJEMPLARES, {"purchase_id": purchase_id}).fetchall()
    return [EjemplarDeCompra(**row) for row in rows]


def guardar_reparto(
    conn: Connection, purchase_id: int, method: str, asignaciones: dict[int, Decimal]
) -> None:
    """Escribe `assigned_cost_usd` de cada ejemplar y el método usado en la
    compra. El `where ... and purchase_id = ...` es un cinturón de
    seguridad: un id que por error no perteneciera a esta compra no se
    toca."""
    for ejemplar_id, costo in asignaciones.items():
        conn.execute(
            _UPDATE_COSTO_ASIGNADO,
            {"id": ejemplar_id, "purchase_id": purchase_id, "costo": costo},
        )
    guardar_metodo(conn, purchase_id, method)
