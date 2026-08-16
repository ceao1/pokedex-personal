create table app.binder (
  id            bigint generated always as identity primary key,
  name          text not null,
  description   text,
  cards_per_page integer not null default 9
);

create table app.owned_copy (
  id              bigint generated always as identity primary key,
  client_draft_id uuid not null unique,
  card_id         text references app.card (id),
  variant_id      text,
  variant_label   text,
  condition       text,
  graded          boolean not null default false,
  grading_company text,
  grade           numeric(4, 1),
  photo_front_url text,
  photo_thumb_url text,
  purchase_price_usd numeric(12, 2),
  source_type     text,
  binder_id       bigint references app.binder (id),
  page            integer,
  capture_status  text not null default 'borrador',
  lifecycle_status text not null default 'en_binder',
  identification_corrected boolean not null default false,
  notes           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint owned_copy_variante_completa foreign key (card_id, variant_id)
    references app.card_variant (card_id, id),
  constraint owned_copy_capture_status_valido check (
    capture_status in ('borrador', 'identificando', 'en_revision', 'listo')
  ),
  constraint owned_copy_lifecycle_status_valido check (
    lifecycle_status in ('en_transito', 'en_binder', 'vendida')
  ),
  constraint owned_copy_condition_valida check (
    condition is null or condition in ('NM', 'LP', 'MP', 'HP', 'DMG')
  ),
  constraint owned_copy_variant_label_valida check (
    variant_label is null or variant_label in (
      'normal', 'reverse', 'holo', 'first_edition', 'shadowless', 'unlimited'
    )
  ),
  constraint owned_copy_gradeo_coherente check (
    (graded = false and grading_company is null and grade is null)
    or (graded = true and grading_company is not null)
  )
);

create index owned_copy_card_idx on app.owned_copy (card_id);
create index owned_copy_binder_idx on app.owned_copy (binder_id);
create index owned_copy_capture_status_idx on app.owned_copy (capture_status)
  where capture_status <> 'listo';

alter table app.binder enable row level security;
alter table app.owned_copy enable row level security;
