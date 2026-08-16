-- La compra pasa a ser el contenedor (plan "Compras: sobres, lotes y fotos
-- por tanda"). Hoy la unidad de captura es la carta; con un sobre de diez
-- cartas y un solo precio, eso deja de alcanzar. Cada ejemplar puede colgar
-- de una compra, y el costo se reparte al final con un método recalculable.
create table app.purchase (
  id                bigint generated always as identity primary key,
  fecha             date not null default current_date,
  source_type       text not null,
  total_usd         numeric(12, 2) not null,
  allocation_method text not null default 'market_value',
  photo_url         text,
  notes             text,
  created_at        timestamptz not null default now(),
  constraint purchase_source_valida check (
    source_type in ('sobre', 'lote', 'tienda', 'online', 'intercambio', 'regalo')
  ),
  constraint purchase_metodo_valido check (
    allocation_method in ('market_value', 'manual', 'equal')
  ),
  constraint purchase_total_no_negativo check (total_usd >= 0)
);

-- `on delete set null` y no `cascade`: borrar una compra registrada por
-- error no puede llevarse por delante las cartas, que existen físicamente.
alter table app.owned_copy
  add column purchase_id bigint references app.purchase (id) on delete set null,
  add column assigned_cost_usd numeric(12, 2),
  add column is_bulk boolean not null default false;

create index owned_copy_purchase_idx on app.owned_copy (purchase_id);
alter table app.purchase enable row level security;

-- El costo efectivo de un ejemplar se lee en un único sitio, nunca eligiendo
-- columna a mano en cada consulta (si no, tarde o temprano un informe suma
-- `purchase_price_usd` donde debía sumar `assigned_cost_usd`, o viceversa).
-- `purchase_price_usd` es el respaldo histórico -- lo que un ejemplar sin
-- compra siguió usando siempre -- y desaparecerá cuando todo ejemplar
-- cuelgue de una compra. Recibe la fila completa; se llama de forma
-- explícita como `app.owned_copy_costo(o)` -- la sintaxis de
-- función-como-columna de Postgres (`o.owned_copy_costo`) solo resuelve sin
-- calificar el esquema cuando `app` está en el `search_path`, que acá no lo
-- está (ver `create_app_schema.sql`: `anon`/`authenticated` ni ven el
-- esquema).
create function app.owned_copy_costo(o app.owned_copy) returns numeric
language sql immutable as $$
  select coalesce(o.assigned_cost_usd, o.purchase_price_usd)
$$;
