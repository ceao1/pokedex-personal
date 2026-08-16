"""Persistencia de los ejemplares en captura. SQL plano, sin ORM.

`photo_front_url` / `photo_thumb_url` guardan el *path* del objeto en el
bucket (`<client_draft_id>/front.jpg`), nunca una URL firmada: una firmada
expira, y persistirla la dejaría rota. El servicio es quien la vuelve a
firmar al servirla.
"""

from uuid import UUID

from psycopg import Connection

from .models import OwnedCopy, OwnedCopyIn

_COLUMNS = """
    id, client_draft_id, card_id, variant_id, variant_label, condition,
    photo_front_url, photo_thumb_url, purchase_price_usd, source_type,
    binder_id, page, capture_status, lifecycle_status, notes, created_at
"""

_INSERT_BORRADOR = """
insert into app.owned_copy (client_draft_id)
values (%(client_draft_id)s)
on conflict (client_draft_id) do nothing
"""

_SELECT_BY_DRAFT = f"""
select {_COLUMNS}
from app.owned_copy
where client_draft_id = %(client_draft_id)s
"""

_UPDATE_FOTOS = """
update app.owned_copy
set photo_front_url = %(front)s,
    photo_thumb_url = %(thumb)s,
    updated_at = now()
where client_draft_id = %(client_draft_id)s
"""

_LIST_PENDIENTES = f"""
select {_COLUMNS}
from app.owned_copy
where capture_status <> 'listo'
order by created_at
"""

# Todas las columnas que `OwnedCopyIn` puede tocar, en el orden en que se
# arma el SET dinámico -- incluye `card_id`/`variant_id` porque el flujo de
# identificación de la carta también viaja como un PATCH más.
_PATCH_FIELDS = (
    "card_id",
    "variant_id",
    "variant_label",
    "condition",
    "purchase_price_usd",
    "source_type",
    "binder_id",
    "page",
    "capture_status",
    "lifecycle_status",
    "notes",
)


def crear_borrador(conn: Connection, client_draft_id: UUID) -> OwnedCopy:
    """Idempotente: reenviar el mismo `client_draft_id` no duplica la fila."""
    conn.execute(_INSERT_BORRADOR, {"client_draft_id": client_draft_id})
    borrador = obtener(conn, client_draft_id)
    assert borrador is not None  # acaba de insertarse (o ya existía)
    return borrador


def actualizar(conn: Connection, client_draft_id: UUID, datos: OwnedCopyIn) -> OwnedCopy | None:
    """PATCH parcial: solo toca los campos que `datos` trae con valor.

    Un `update` armado con cero columnas es SQL inválido (`set` sin nada
    detrás), y eso es justo lo que produce un celular reenviando un PATCH sin
    cambios -- así que ese caso no genera SQL en absoluto y simplemente
    devuelve el estado actual.
    """
    valores = {campo: getattr(datos, campo) for campo in _PATCH_FIELDS}
    a_actualizar = {campo: valor for campo, valor in valores.items() if valor is not None}

    if not a_actualizar:
        return obtener(conn, client_draft_id)

    set_clause = ", ".join(f"{campo} = %({campo})s" for campo in a_actualizar)
    sql = f"""
        update app.owned_copy
        set {set_clause}, updated_at = now()
        where client_draft_id = %(client_draft_id)s
    """
    params = {**a_actualizar, "client_draft_id": client_draft_id}
    conn.execute(sql, params)
    return obtener(conn, client_draft_id)


def guardar_fotos(conn: Connection, client_draft_id: UUID, front: str, thumb: str) -> None:
    conn.execute(
        _UPDATE_FOTOS,
        {"front": front, "thumb": thumb, "client_draft_id": client_draft_id},
    )


def obtener(conn: Connection, client_draft_id: UUID) -> OwnedCopy | None:
    row = conn.execute(_SELECT_BY_DRAFT, {"client_draft_id": client_draft_id}).fetchone()
    return OwnedCopy(**row) if row is not None else None


def listar_pendientes(conn: Connection) -> list[OwnedCopy]:
    rows = conn.execute(_LIST_PENDIENTES).fetchall()
    return [OwnedCopy(**row) for row in rows]
