"""Persistencia del espejo del catálogo. SQL plano, sin ORM."""

from psycopg import Connection
from psycopg.types.json import Jsonb

from .models import Card, CardVariant

_UPSERT_CARD = """
insert into app.card (
    id, name, set_id, set_name, local_id, set_card_count,
    rarity, image_url, dex_number, raw, cached_at
)
values (
    %(id)s, %(name)s, %(set_id)s, %(set_name)s, %(local_id)s, %(set_card_count)s,
    %(rarity)s, %(image_url)s, %(dex_number)s, %(raw)s, now()
)
on conflict (id) do update set
    name           = excluded.name,
    set_id         = excluded.set_id,
    set_name       = excluded.set_name,
    local_id       = excluded.local_id,
    set_card_count = excluded.set_card_count,
    rarity         = excluded.rarity,
    image_url      = excluded.image_url,
    dex_number     = excluded.dex_number,
    raw            = excluded.raw,
    cached_at      = now()
"""

_UPSERT_VARIANT = """
insert into app.card_variant (
    id, card_id, type, subtype, stamp, foil, size, price_usd, price_captured_at, raw
)
values (
    %(id)s, %(card_id)s, %(type)s, %(subtype)s, %(stamp)s, %(foil)s, %(size)s,
    %(price_usd)s, %(price_captured_at)s, %(raw)s
)
on conflict (card_id, id) do update set
    type              = excluded.type,
    subtype           = excluded.subtype,
    stamp             = excluded.stamp,
    foil              = excluded.foil,
    size              = excluded.size,
    price_usd         = excluded.price_usd,
    price_captured_at = excluded.price_captured_at,
    raw               = excluded.raw
"""

_SELECT_CARD = """
select id, name, set_id, set_name, local_id, set_card_count,
       rarity, image_url, dex_number, raw
from app.card
where {condition}
"""

_SELECT_VARIANTS = """
select id, type, subtype, stamp, foil, size, price_usd, price_captured_at, raw
from app.card_variant
where card_id = %(card_id)s
order by id
"""


def upsert_card(conn: Connection, card: Card) -> None:
    """Escribe la carta y sus variantes de forma atómica."""
    with conn.transaction():
        conn.execute(
            _UPSERT_CARD,
            {
                "id": card.id,
                "name": card.name,
                "set_id": card.set_id,
                "set_name": card.set_name,
                "local_id": card.local_id,
                "set_card_count": card.set_card_count,
                "rarity": card.rarity,
                "image_url": card.image_url,
                "dex_number": card.dex_number,
                # Jsonb y no json.dumps: un str crudo choca contra la columna
                # jsonb con "column raw is of type jsonb but expression is of type text".
                "raw": Jsonb(card.raw),
            },
        )
        for variant in card.variants:
            conn.execute(
                _UPSERT_VARIANT,
                {
                    "id": variant.id,
                    "card_id": card.id,
                    "type": variant.type,
                    "subtype": variant.subtype,
                    "stamp": variant.stamp,
                    "foil": variant.foil,
                    "size": variant.size,
                    "price_usd": variant.price_usd,
                    "price_captured_at": variant.price_captured_at,
                    "raw": Jsonb(variant.raw),
                },
            )


def _load(conn: Connection, condition: str, params: dict) -> Card | None:
    row = conn.execute(_SELECT_CARD.format(condition=condition), params).fetchone()
    if row is None:
        return None
    variant_rows = conn.execute(_SELECT_VARIANTS, {"card_id": row["id"]}).fetchall()
    return Card(**row, variants=[CardVariant(**v) for v in variant_rows])


def get_card(conn: Connection, card_id: str) -> Card | None:
    return _load(conn, "id = %(id)s", {"id": card_id})


def find_by_set_and_number(conn: Connection, set_id: str, local_id: str) -> Card | None:
    return _load(
        conn,
        "set_id = %(set_id)s and local_id = %(local_id)s",
        {"set_id": set_id, "local_id": local_id},
    )
