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
    binder_id, page, capture_status, lifecycle_status, notes, dex_number,
    purchase_id, assigned_cost_usd, is_bulk, created_at
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

# Ejemplares de un Pokémon puntual, para la ficha (spec: "varios ejemplares
# por Pokémon"). `left join` (no `join`) a propósito: un ejemplar puede
# colgar de este casillero por su propio `dex_number` (task "identificar por
# lo impreso en la carta" -- especie confirmada, carta exacta desconocida)
# sin tener `card_id` todavía. `coalesce(c.dex_number, o.dex_number)` -- la
# carta manda cuando existe, el valor propio del ejemplar es el respaldo --
# es la misma regla en `wishlist.repository` (`owned_count`) y en
# `listar_fuera_del_151`, abajo: que las tres diverjan sería reabrir el
# agujero negro que ya cerró `listar_fuera_del_151`. Trae ya el nombre, el
# set, el arte, la rareza y el `local_id` de la carta cuando existe, para
# que la ficha se dibuje sin una segunda consulta -- todo `null` si no hay
# carta todavía. Excluye las vendidas: una carta que ya no está en el
# binder no es un ejemplar que el dueño "tiene".
#
# `purchase_price_usd` acá es el costo EFECTIVO -- `app.owned_copy_costo(o)`,
# `coalesce(assigned_cost_usd, purchase_price_usd)`, el único sitio donde se
# decide (ver la migración de `app.purchase`) -- no la columna cruda. Esta
# vista es de solo lectura (nadie hace `UPDATE` contra estas filas), así que
# alias el nombre no mezcla lectura con escritura como sí lo haría en
# `_COLUMNS`/`OwnedCopy` (ver el comentario de `purchase_price_usd` en
# `models.py`): sin esto, un ejemplar que salió de una compra mostraría costo
# nulo en la ficha aunque el reparto ya le haya asignado uno.
_LISTAR_POR_DEX = """
select o.id, o.card_id, c.name as card_name, c.set_name, c.local_id,
       c.image_url, c.rarity, o.variant_label, o.condition,
       app.owned_copy_costo(o) as purchase_price_usd,
       o.photo_front_url, o.photo_thumb_url,
       o.notes, o.created_at
from app.owned_copy o
left join app.card c on c.id = o.card_id
where coalesce(c.dex_number, o.dex_number) = %(dex_number)s
  and o.lifecycle_status <> 'vendida'
-- `created_at` es hora de transacción: varios ejemplares insertados en la
-- misma transacción comparten el mismo valor. `id` desempata de forma
-- estable (los ids son consecutivos, así que el más reciente tiene el mayor).
order by o.created_at desc, o.id desc
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
    "dex_number",
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


def listar_por_dex(conn: Connection, dex_number: int) -> list[dict]:
    """Los ejemplares que el dueño ya tiene de un Pokémon puntual, más
    recientes primero. Filas planas (no `OwnedCopy`): traen columnas de
    `card` que ese modelo no tiene, para que la ficha del Pokémon se dibuje
    sin una segunda consulta."""
    return conn.execute(_LISTAR_POR_DEX, {"dex_number": dex_number}).fetchall()


# El binder recorre `app.pokemon` (151 filas): un ejemplar cuyo dex_number
# efectivo (`coalesce(c.dex_number, o.dex_number)` -- ver `_LISTAR_POR_DEX`,
# arriba) no cae entre 1 y 151 no aparece en ninguna consulta ahí y se
# esfuma en silencio -- el agujero negro que esta consulta cierra. `left
# join` a `app.card` (no `join`) a propósito: un ejemplar sin `card_id`
# todavía (capturado con foto y precio, sin resolver, y sin `dex_number`
# propio tampoco) también queda fuera del proyecto y tiene que aparecer, y
# un `join` liso lo excluiría.
# `purchase_price_usd` acá también es el costo efectivo, no la columna cruda
# -- mismo motivo que en `_LISTAR_POR_DEX`, arriba.
_LISTAR_FUERA_DEL_151 = """
select o.id, o.card_id, c.name as card_name, c.set_name, c.local_id,
       coalesce(c.dex_number, o.dex_number) as dex_number,
       c.image_url, o.variant_label, o.condition,
       app.owned_copy_costo(o) as purchase_price_usd,
       o.photo_front_url, o.photo_thumb_url, o.notes, o.created_at
from app.owned_copy o
left join app.card c on c.id = o.card_id
where (
    coalesce(c.dex_number, o.dex_number) is null
    or coalesce(c.dex_number, o.dex_number) not between 1 and 151
  )
  and o.lifecycle_status <> 'vendida'
order by o.created_at desc, o.id desc
"""


def listar_fuera_del_151(conn: Connection) -> list[dict]:
    """Los ejemplares cuya carta no pertenece al proyecto de los 151: de otra
    generación, sin `dex_number` en el catálogo, o sin carta identificada
    todavía. Excluye las vendidas, igual que `listar_por_dex`. Filas planas,
    no `OwnedCopy`: traen columnas de `card` que ese modelo no tiene."""
    return conn.execute(_LISTAR_FUERA_DEL_151).fetchall()
