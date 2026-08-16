"""Persistencia del checklist y la wishlist. SQL plano, sin ORM."""

from psycopg import Connection

from .models import WishlistItemIn

_UPSERT_POKEMON = """
insert into app.pokemon (dex_number, name)
values (%(dex_number)s, %(name)s)
on conflict (dex_number) do update set name = excluded.name
"""

# Dos upserts porque los índices únicos son parciales y excluyentes: uno para
# los items resueltos (llaveados por carta y variante) y otro para los que no
# resolvieron (llaveados por su texto original).
_UPSERT_RESUELTO = """
insert into app.wishlist_item
    (dex_number, card_id, variant_label, raw_text, source_option,
     auto_resolved, is_favorite, reference_value_usd)
values
    (%(dex_number)s, %(card_id)s, %(variant_label)s, %(raw_text)s, %(source_option)s,
     %(auto_resolved)s, %(is_favorite)s, %(reference_value_usd)s)
on conflict (dex_number, card_id, variant_label) where card_id is not null
do update set
    raw_text            = excluded.raw_text,
    -- No se pisa: "gana el primero que resolvió esta clave". Si se
    -- actualizara, una fila de la galería que fusiona sobre la clave de
    -- otra opción le robaría el source_option (y con él, el orden que usa
    -- `primary_image_url` en `_LIST_POKEDEX` para elegir la ruta barata).
    is_favorite         = app.wishlist_item.is_favorite or excluded.is_favorite,
    reference_value_usd = excluded.reference_value_usd,
    updated_at          = now()
"""

_UPSERT_SIN_RESOLVER = """
insert into app.wishlist_item
    (dex_number, card_id, variant_label, raw_text, source_option,
     auto_resolved, is_favorite, reference_value_usd)
values
    (%(dex_number)s, null, null, %(raw_text)s, %(source_option)s,
     %(auto_resolved)s, %(is_favorite)s, %(reference_value_usd)s)
on conflict (dex_number, raw_text) where card_id is null
do update set
    -- Mismo criterio que en _UPSERT_RESUELTO: no se pisa el source_option
    -- del primero que insertó esta clave.
    is_favorite         = app.wishlist_item.is_favorite or excluded.is_favorite,
    reference_value_usd = excluded.reference_value_usd,
    updated_at          = now()
"""

# `(card_id, type)` no es único: una carta puede tener una variante `normal`
# simple y otra con sello o foil, ambas del mismo `type`. Un `left join` liso
# contra `app.card_variant` multiplicaría la fila del item por cada una. Se
# usa `left join lateral ... limit 1` (una subconsulta correlacionada) para
# que cada item aporte a lo sumo una fila de variante, eligiendo la menos
# exótica. El orden debe mantenerse en sincronía con
# `catalog.variants._specificity`, que aplica el mismo criterio en Python
# para elegir la variante que el usuario marcó.
#
# El `case` de abajo es la traducción a SQL de `catalog.variants._matches`
# (ver el comentario simétrico ahí): esa función es la autoridad sobre qué
# significa cada `variant_label`, y solo tres de las seis etiquetas viven en
# la columna `type` -- `unlimited` y `shadowless` viven en `subtype`, y
# `first_edition` mira el arreglo `stamp`. Si `_matches` cambia, este `case`
# tiene que cambiar con ella; que no diverjan es lo que impide un bug de
# "156 de 421 items sin precio".
_VARIANTE_PREFERIDA = """
    select v.price_usd, v.price_captured_at
    from app.card_variant v
    where v.card_id = w.card_id
      and case w.variant_label
            when 'normal'        then v.type = 'normal'
            when 'reverse'       then v.type = 'reverse'
            when 'holo'          then v.type = 'holo' and v.subtype is null
            when 'first_edition' then '1st-edition' = any(v.stamp)
            when 'shadowless'    then v.subtype = 'shadowless'
                                       and not ('1st-edition' = any(v.stamp))
            when 'unlimited'     then v.subtype = 'unlimited'
            else false
          end
    order by (v.stamp <> '{}')::int, (v.foil is not null)::int, v.id
    limit 1
"""

_LIST_WISHLIST = f"""
select w.id, w.dex_number, w.card_id, w.variant_label, w.raw_text, w.source_option,
       w.auto_resolved, w.is_favorite, w.status, w.reference_value_usd,
       c.name as card_name, c.image_url, c.rarity, c.set_name,
       v.price_usd, v.price_captured_at
from app.wishlist_item w
left join app.card c on c.id = w.card_id
left join lateral ({_VARIANTE_PREFERIDA}) v on true
where (%(dex_number)s::integer is null or w.dex_number = %(dex_number)s::integer)
order by w.dex_number, w.source_option
"""

_LIST_POKEDEX = f"""
select p.dex_number,
       p.name,
       count(w.id) as wishlist_count,
       count(w.id) filter (where w.card_id is null) as sin_resolver,
       -- Ejemplares en posesión, excluyendo los vendidos. Subconsulta escalar
       -- y no join: un join multiplicaría las filas ya agrupadas por p.dex_number.
       (select count(*)
          from app.owned_copy o
          join app.card oc on oc.id = o.card_id
         where oc.dex_number = p.dex_number
           and o.lifecycle_status <> 'vendida') as owned_count,
       -- Carta y precio de la ruta preferida. `source_option` ordena
       -- alfabéticamente y 'opcion_1' es la primera, así que esto devuelve la
       -- ruta económica del set 151 cuando resolvió.
       (array_agg(c.image_url order by w.source_option)
          filter (where c.image_url is not null))[1] as primary_image_url,
       (array_agg(c.name order by w.source_option)
          filter (where c.image_url is not null))[1] as primary_card_name,
       (array_agg(v.price_usd order by w.source_option)
          filter (where v.price_usd is not null))[1] as primary_price_usd,
       -- Misma máscara de filtro que primary_price_usd: el precio y su
       -- fecha de congelado (spec §11/§15) tienen que venir del mismo par
       -- (card_id, variant_label), o la fecha quedaría describiendo un
       -- precio distinto del que se muestra.
       (array_agg(v.price_captured_at order by w.source_option)
          filter (where v.price_usd is not null))[1] as primary_price_captured_at
from app.pokemon p
left join app.wishlist_item w on w.dex_number = p.dex_number
left join app.card c on c.id = w.card_id
left join lateral ({_VARIANTE_PREFERIDA}) v on true
group by p.dex_number, p.name
order by p.dex_number
"""


def upsert_pokemon(conn: Connection, dex_number: int, name: str) -> None:
    conn.execute(_UPSERT_POKEMON, {"dex_number": dex_number, "name": name})


def upsert_wishlist_item(conn: Connection, item: WishlistItemIn) -> None:
    """Idempotente. No pisa `auto_resolved`: una vez que el humano corrigió un
    item (poniéndolo en false), el reimport deja esa marca en paz."""
    sql = _UPSERT_RESUELTO if item.card_id is not None else _UPSERT_SIN_RESOLVER
    conn.execute(sql, item.model_dump())


def list_wishlist(conn: Connection, dex_number: int | None = None) -> list[dict]:
    return conn.execute(_LIST_WISHLIST, {"dex_number": dex_number}).fetchall()


def list_pokedex(conn: Connection) -> list[dict]:
    return conn.execute(_LIST_POKEDEX).fetchall()
