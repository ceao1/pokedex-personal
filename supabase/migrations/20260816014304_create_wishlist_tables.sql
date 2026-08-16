create table app.pokemon (
  dex_number integer primary key,
  name       text not null
);

create table app.wishlist_item (
  id                  bigint generated always as identity primary key,
  dex_number          integer references app.pokemon (dex_number),
  card_id             text references app.card (id),
  variant_label       text,
  raw_text            text not null,
  source_option       text not null,
  auto_resolved       boolean not null default false,
  is_favorite         boolean not null default false,
  status              text not null default 'deseada',
  target_price_usd    numeric(12, 2),
  reference_value_usd numeric(12, 2),
  priority            integer,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  constraint wishlist_item_source_option_valida check (
    source_option in ('opcion_1', 'opcion_2', 'opcion_3', 'opcion_4', 'galeria', 'manual')
  ),
  constraint wishlist_item_status_valido check (
    status in ('deseada', 'cazando', 'comprada_en_transito')
  ),
  constraint wishlist_item_variant_valida check (
    variant_label is null or variant_label in (
      'normal', 'reverse', 'holo', 'first_edition', 'shadowless', 'unlimited'
    )
  )
);

create unique index wishlist_item_resuelto_idx
  on app.wishlist_item (dex_number, card_id, variant_label)
  where card_id is not null;

create unique index wishlist_item_sin_resolver_idx
  on app.wishlist_item (dex_number, raw_text)
  where card_id is null;

create index wishlist_item_dex_idx on app.wishlist_item (dex_number);
create index wishlist_item_card_idx on app.wishlist_item (card_id);

alter table app.pokemon enable row level security;
alter table app.wishlist_item enable row level security;
