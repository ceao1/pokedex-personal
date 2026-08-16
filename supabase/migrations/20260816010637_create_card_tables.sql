create table app.card (
  id             text primary key,
  name           text not null,
  set_id         text not null,
  set_name       text not null,
  local_id       text not null,
  set_card_count integer,
  rarity         text,
  image_url      text,
  dex_number     integer,
  raw            jsonb not null,
  cached_at      timestamptz not null default now()
);

create unique index card_set_local_idx on app.card (set_id, local_id);
create index card_dex_number_idx on app.card (dex_number) where dex_number is not null;

create table app.card_variant (
  id                text primary key,
  card_id           text not null references app.card (id) on delete cascade,
  type              text not null,
  subtype           text,
  stamp             text[] not null default '{}',
  foil              text,
  size              text,
  price_usd         numeric(12, 2),
  price_captured_at timestamptz,
  raw               jsonb not null,
  constraint card_variant_price_pareja check (
    (price_usd is null) = (price_captured_at is null)
  )
);

create index card_variant_card_id_idx on app.card_variant (card_id);

alter table app.card enable row level security;
alter table app.card_variant enable row level security;
