# Captura de ejemplares — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrar una carta física con su foto propia en menos de 30 segundos desde el celular, y que el bolsillo del binder pase de gris a color.

**Architecture:** "Foto primero, enriquecer después" (spec D12). La foto sube directo a Supabase Storage con URL firmada, nace un `owned_copy` en borrador, y el resto son PATCHes idempotentes contra el `client_draft_id` que genera el celular. La identificación vive detrás de `RecognitionPort`; en este plan el adaptador es manual (el humano elige la carta) y el automático por visión entra después sin tocar el resto.

**Tech Stack:** El mismo (FastAPI, psycopg 3, Pydantic v2, Next.js 16, CSS Modules), más Supabase Storage.

**Spec:** `docs/superpowers/specs/2026-08-15-pokedex-viviente-design.md`
**Planes previos:** fundación y catálogo, checklist e import, frontend del binder — los tres completos.

## Global Constraints

- **Las tablas viven en el esquema `app`**, RLS habilitada, sin políticas para `anon` ni `authenticated`.
- **Moneda única USD**, `Decimal` en Python, `float` solo en el borde HTTP.
- **Ningún test de la suite por defecto puede pegarle a la red.** El Storage local de Supabase no cuenta como red, igual que el Postgres local.
- **El frontend habla solo con FastAPI.** Excepción ya existente: el arte de las cartas viene del CDN de TCGdex, que el backend espeja como URL.
- **La llave secreta (`sb_secret_...`) solo en el backend.** El navegador nunca la ve; sube con URL firmada.
- **Copy en español**, sentence case, voz activa.
- **`variant_label`** usa `pokedex.catalog.variants.VariantLabel`.
- **La identidad de una variante es `(card_id, variant_id)`**, nunca `variant_id` solo.

## Por qué no hay identificación automática todavía

`RecognitionPort` se define en este plan y su única implementación es `ManualRecognition`, que no adivina: devuelve siempre "necesita revisión" y deja que el humano elija la carta. El adaptador de visión necesita una llave de API que no existe en este entorno; cuando exista, se agrega una clase que cumple el mismo puerto y nada más cambia.

Eso no es una limitación del diseño, es el diseño: el spec ya exige que el output de visión solo se acepte si el número de colección hace match exacto, así que la ruta manual es el camino de respaldo obligatorio de todos modos.

---

## Task 1: Tablas `owned_copy` y `binder`

**Files:**
- Create: `supabase/migrations/<ts>_create_owned_copy.sql`
- Test: `backend/tests/collection/test_schema.py`
- Create: `backend/tests/collection/__init__.py`
- Modify: `backend/tests/conftest.py` (ampliar el truncate de `clean_db`)

**Interfaces:**
- Produces: `app.binder`, `app.owned_copy`

- [ ] **Step 1: Crear la migración**

```bash
supabase migration new create_owned_copy
```

- [ ] **Step 2: Escribir el DDL**

```sql
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
```

Notas sobre las decisiones:
- La foránea compuesta `(card_id, variant_id) → app.card_variant (card_id, id)` es la que impide guardar un ejemplar con una variante que no pertenece a su carta. Es posible justamente porque el fix del `variantId` hizo que la identidad de la variante sea el par.
- `capture_status` y `lifecycle_status` son ejes separados (spec §5): una carta puede estar en el binder y aún con la identificación en revisión.
- El índice de `capture_status` es parcial: solo interesa buscar lo que está pendiente, y en régimen la inmensa mayoría estará en `listo`.
- `owned_copy_gradeo_coherente` impide el estado "gradeada sin empresa", que haría imposible interpretar la nota.

- [ ] **Step 3: Ampliar `clean_db`**

En `backend/tests/conftest.py`, el truncate del fixture pasa a incluir las tablas nuevas, tanto en el setup como en el teardown:

```python
"truncate app.card, app.pokemon, app.wishlist_item, app.owned_copy, app.binder cascade"
```

- [ ] **Step 4: Escribir los tests**

`backend/tests/collection/test_schema.py`:

```python
import psycopg
import pytest


def _sembrar_carta_con_variante(conn, card_id="sv03.5-001", variant_id="v-normal"):
    conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, raw)
        values (%s, 'Bulbasaur', 'sv03.5', '151', '001', '{}'::jsonb)
        on conflict do nothing
        """,
        (card_id,),
    )
    conn.execute(
        """
        insert into app.card_variant (id, card_id, type, raw)
        values (%s, %s, 'normal', '{}'::jsonb)
        on conflict do nothing
        """,
        (variant_id, card_id),
    )


def test_las_tablas_de_coleccion_existen_con_rls(db_conn):
    rows = db_conn.execute(
        """
        select c.relname, c.relrowsecurity
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'app' and c.relkind = 'r'
        """
    ).fetchall()
    por_nombre = {r["relname"]: r["relrowsecurity"] for r in rows}
    assert "owned_copy" in por_nombre
    assert "binder" in por_nombre
    sin_rls = [n for n, rls in por_nombre.items() if not rls]
    assert sin_rls == [], f"tablas de app sin RLS: {sin_rls}"


def test_un_ejemplar_minimo_se_guarda(clean_db):
    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id)
        values ('11111111-1111-1111-1111-111111111111')
        """
    )
    fila = clean_db.execute(
        "select capture_status, lifecycle_status, graded from app.owned_copy"
    ).fetchone()
    assert fila["capture_status"] == "borrador"
    assert fila["lifecycle_status"] == "en_binder"
    assert fila["graded"] is False


def test_el_client_draft_id_es_unico(clean_db):
    for _ in range(2):
        try:
            clean_db.execute(
                """
                insert into app.owned_copy (client_draft_id)
                values ('22222222-2222-2222-2222-222222222222')
                """
            )
        except psycopg.errors.UniqueViolation:
            return
    raise AssertionError("se permitió duplicar client_draft_id")


def test_no_se_puede_asignar_una_variante_de_otra_carta(clean_db):
    """La foránea compuesta es lo que impide guardar un Bulbasaur con la
    variante de un Charizard."""
    _sembrar_carta_con_variante(clean_db, "sv03.5-001", "v-a")
    _sembrar_carta_con_variante(clean_db, "sv03.5-002", "v-b")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        clean_db.execute(
            """
            insert into app.owned_copy (client_draft_id, card_id, variant_id)
            values ('33333333-3333-3333-3333-333333333333', 'sv03.5-001', 'v-b')
            """
        )


def test_gradeada_sin_empresa_se_rechaza(clean_db):
    with pytest.raises(psycopg.errors.CheckViolation):
        clean_db.execute(
            """
            insert into app.owned_copy (client_draft_id, graded)
            values ('44444444-4444-4444-4444-444444444444', true)
            """
        )


def test_un_capture_status_invalido_se_rechaza(clean_db):
    with pytest.raises(psycopg.errors.CheckViolation):
        clean_db.execute(
            """
            insert into app.owned_copy (client_draft_id, capture_status)
            values ('55555555-5555-5555-5555-555555555555', 'inventado')
            """
        )
```

- [ ] **Step 5: Aplicar, verificar y commitear**

```bash
supabase db reset
cd backend && uv run pytest tests/collection/ -v
supabase db advisors
cd .. && git add supabase/migrations backend/tests
git commit -m "feat: tablas owned_copy y binder con foránea compuesta de variante"
```

**Nota importante:** `supabase db reset` borra los datos importados. Después de esta task hay que re-correr el import:
`cd backend && PYTHONPATH=src uv run python -m pokedex.cli import-excel ../Pokedex_Viviente_151.xlsx`

---

## Task 2: `owned_count` deja de ser cero

El literal `0::int` que el plan anterior puso en el SQL con un comentario que decía qué cambiar. Ha llegado el momento.

**Files:**
- Modify: `backend/src/pokedex/wishlist/repository.py`
- Test: `backend/tests/wishlist/test_repository.py`
- Test: `backend/tests/wishlist/test_service.py` (activar el test que estaba saltado)

- [ ] **Step 1: Escribir los tests (que van a fallar)**

En `backend/tests/wishlist/test_repository.py`:

```python
def test_owned_count_cuenta_ejemplares_reales(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["owned_count"] == 0

    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id)
        values ('66666666-6666-6666-6666-666666666666', 'sv03.5-001')
        """
    )
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["owned_count"] == 1


def test_una_carta_vendida_no_cuenta_como_conseguida(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, lifecycle_status)
        values ('77777777-7777-7777-7777-777777777777', 'sv03.5-001', 'vendida')
        """
    )
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["owned_count"] == 0


def test_dos_ejemplares_de_la_misma_carta_cuentan_dos(clean_db):
    """Un duplicado es un ejemplar más, no un Pokémon más — el progreso del
    151 se calcula sobre Pokémon distintos, no sobre este conteo."""
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    for uuid_ in ("88888888-8888-8888-8888-888888888888",
                  "99999999-9999-9999-9999-999999999999"):
        clean_db.execute(
            "insert into app.owned_copy (client_draft_id, card_id) values (%s, 'sv03.5-001')",
            (uuid_,),
        )
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["owned_count"] == 2
```

- [ ] **Step 2: Cambiar el SQL**

En `_LIST_POKEDEX`, reemplazar el literal por el conteo real. Un ejemplar cuenta cuando no está vendido:

```sql
       (select count(*)
          from app.owned_copy o
          join app.card oc on oc.id = o.card_id
         where oc.dex_number = p.dex_number
           and o.lifecycle_status <> 'vendida') as owned_count,
```

Va como subconsulta escalar y no como join, por la misma razón que el precio: un join multiplicaría las filas del agrupado.

- [ ] **Step 3: Activar el test que estaba saltado**

En `backend/tests/wishlist/test_service.py`, quitar el `pytest.skip` de `test_el_import_no_crea_ejemplares`. La tabla ya existe, así que el test pasa a ser real: el import siembra checklist y wishlist y deja `app.owned_copy` vacía.

- [ ] **Step 4: Correr y commitear**

```bash
cd backend && uv run pytest -q
git add backend && git commit -m "feat: owned_count cuenta ejemplares reales"
```

---

## Task 3: Storage y endpoints de captura

**Files:**
- Create: `supabase/migrations/<ts>_create_storage_bucket.sql`
- Create: `backend/src/pokedex/collection/__init__.py`
- Create: `backend/src/pokedex/collection/models.py`
- Create: `backend/src/pokedex/collection/storage.py`
- Create: `backend/src/pokedex/collection/repository.py`
- Create: `backend/src/pokedex/collection/service.py`
- Create: `backend/src/pokedex/api/routes/capture.py`
- Modify: `backend/src/pokedex/api/main.py`
- Modify: `backend/src/pokedex/config.py`
- Test: `backend/tests/collection/test_repository.py`
- Test: `backend/tests/api/test_capture_routes.py`

**Interfaces:**
- Produces:
  - `StoragePort` con `async create_signed_upload(path) -> SignedUpload` y `async signed_download_url(path, seconds) -> str`
  - `SupabaseStorage` (adaptador real) y `FakeStorage` (para tests)
  - `POST /captures` → `{client_draft_id, uploads: {front, thumb}}`
  - `POST /captures/{client_draft_id}/photo-uploaded`
  - `PATCH /captures/{client_draft_id}`
  - `GET /captures/pendientes`

- [ ] **Step 1: Crear el bucket**

```bash
supabase migration new create_storage_bucket
```

```sql
insert into storage.buckets (id, name, public)
values ('card-photos', 'card-photos', false)
on conflict (id) do nothing;
```

Privado a propósito: las fotos son del dueño y se sirven con URL firmada de corta duración.

- [ ] **Step 2: Ampliar la configuración**

En `backend/src/pokedex/config.py`, añadir:

```python
    supabase_url: str = "http://127.0.0.1:54321"
    supabase_secret_key: str = ""
    storage_bucket: str = "card-photos"
```

Y en `.env.example`:

```
SUPABASE_URL=http://127.0.0.1:54321
# `supabase status -o env` la imprime como SECRET_KEY
SUPABASE_SECRET_KEY=sb_secret_...
STORAGE_BUCKET=card-photos
```

- [ ] **Step 3: Escribir el puerto y el adaptador de Storage**

`backend/src/pokedex/collection/storage.py`:

```python
"""Subida de fotos a Supabase Storage sin exponer la llave secreta.

El backend firma la subida y el navegador sube directo al bucket. Un
multipart desde el celular a través de FastAPI sería el cuello de botella
del flujo de 30 segundos.
"""

from typing import Protocol

import httpx
from pydantic import BaseModel


class SignedUpload(BaseModel):
    path: str
    signed_url: str
    token: str


class StoragePort(Protocol):
    async def create_signed_upload(self, path: str) -> SignedUpload: ...

    async def signed_download_url(self, path: str, seconds: int = 3600) -> str: ...


class SupabaseStorage:
    def __init__(self, base_url: str, secret_key: str, bucket: str,
                 client: httpx.AsyncClient) -> None:
        self._base = f"{base_url.rstrip('/')}/storage/v1"
        self._headers = {"Authorization": f"Bearer {secret_key}", "apikey": secret_key}
        self._bucket = bucket
        self._client = client

    async def create_signed_upload(self, path: str) -> SignedUpload:
        response = await self._client.post(
            f"{self._base}/object/upload/sign/{self._bucket}/{path}",
            headers=self._headers,
            json={},
        )
        response.raise_for_status()
        cuerpo = response.json()
        # La API devuelve la url con el token embebido en query string.
        url = cuerpo["url"]
        token = url.split("token=", 1)[1] if "token=" in url else cuerpo.get("token", "")
        return SignedUpload(
            path=path, signed_url=f"{self._base}/{url.lstrip('/')}", token=token
        )

    async def signed_download_url(self, path: str, seconds: int = 3600) -> str:
        response = await self._client.post(
            f"{self._base}/object/sign/{self._bucket}/{path}",
            headers=self._headers,
            json={"expiresIn": seconds},
        )
        response.raise_for_status()
        return f"{self._base}/{response.json()['signedURL'].lstrip('/')}"
```

- [ ] **Step 4: Escribir modelos, repositorio y servicio**

`backend/src/pokedex/collection/models.py`:

```python
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class OwnedCopyIn(BaseModel):
    """Los campos que el celular puede mandar en un PATCH. Todos opcionales:
    el flujo los va completando en pantallas sucesivas."""

    card_id: str | None = None
    variant_id: str | None = None
    variant_label: str | None = None
    condition: str | None = None
    purchase_price_usd: Decimal | None = None
    source_type: str | None = None
    binder_id: int | None = None
    page: int | None = None
    capture_status: str | None = None
    lifecycle_status: str | None = None
    notes: str | None = None


class OwnedCopy(BaseModel):
    id: int
    client_draft_id: UUID
    card_id: str | None
    variant_id: str | None
    variant_label: str | None
    condition: str | None
    photo_front_url: str | None
    photo_thumb_url: str | None
    purchase_price_usd: Decimal | None
    source_type: str | None
    binder_id: int | None
    page: int | None
    capture_status: str
    lifecycle_status: str
    notes: str | None
    created_at: datetime
```

`backend/src/pokedex/collection/repository.py`: `crear_borrador(conn, client_draft_id) -> OwnedCopy` con `on conflict (client_draft_id) do nothing` más un `select` — así reenviar no duplica; `actualizar(conn, client_draft_id, datos: OwnedCopyIn) -> OwnedCopy | None` que construye el `update` solo con los campos no nulos; `guardar_fotos(conn, client_draft_id, front, thumb)`; `obtener(conn, client_draft_id)`; `listar_pendientes(conn)` filtrando `capture_status <> 'listo'`.

`backend/src/pokedex/collection/service.py` orquesta: pide las dos URLs firmadas al `StoragePort`, crea el borrador, y expone `registrar(...)` para el PATCH.

- [ ] **Step 5: Escribir los tests del repositorio**

`backend/tests/collection/test_repository.py` debe cubrir, como mínimo:

```python
def test_crear_borrador_dos_veces_no_duplica(clean_db):
    from uuid import UUID
    from pokedex.collection import repository

    draft = UUID("aaaaaaaa-0000-0000-0000-000000000001")
    primero = repository.crear_borrador(clean_db, draft)
    segundo = repository.crear_borrador(clean_db, draft)
    assert primero.id == segundo.id
    total = clean_db.execute("select count(*) as n from app.owned_copy").fetchone()["n"]
    assert total == 1


def test_el_patch_solo_toca_los_campos_enviados(clean_db):
    from uuid import UUID
    from pokedex.collection import repository
    from pokedex.collection.models import OwnedCopyIn

    draft = UUID("aaaaaaaa-0000-0000-0000-000000000002")
    repository.crear_borrador(clean_db, draft)
    repository.actualizar(clean_db, draft, OwnedCopyIn(condition="NM", notes="ejemplo"))
    repository.actualizar(clean_db, draft, OwnedCopyIn(condition="LP"))
    fila = repository.obtener(clean_db, draft)
    assert fila.condition == "LP"
    assert fila.notes == "ejemplo", "un PATCH parcial no puede borrar lo que no menciona"


def test_un_patch_vacio_no_revienta(clean_db):
    from uuid import UUID
    from pokedex.collection import repository
    from pokedex.collection.models import OwnedCopyIn

    draft = UUID("aaaaaaaa-0000-0000-0000-000000000003")
    repository.crear_borrador(clean_db, draft)
    assert repository.actualizar(clean_db, draft, OwnedCopyIn()) is not None
```

Ese último importa: un `update` construido dinámicamente con cero columnas genera SQL inválido, y es el error que aparece cuando el celular reenvía un PATCH sin cambios.

- [ ] **Step 6: Escribir las rutas**

`backend/src/pokedex/api/routes/capture.py` con los cuatro endpoints. `POST /captures` acepta un `client_draft_id` generado en el cliente y devuelve las dos subidas firmadas. `PATCH` acepta `OwnedCopyIn` y devuelve el ejemplar. Los tests sustituyen `StoragePort` por un fake, como ya se hace con el catálogo.

- [ ] **Step 7: Montar el router, correr y commitear**

---

## Task 4: Registrar una carta desde el navegador

**Files:**
- Create: `frontend/app/registrar/page.tsx`
- Create: `frontend/app/registrar/Captura.tsx`
- Create: `frontend/app/registrar/Captura.module.css`
- Modify: `frontend/app/lib/api.ts`
- Modify: `frontend/app/lib/types.ts`
- Modify: `frontend/app/binder/Rail.tsx` (enlace a registrar)

- [ ] **Step 1: Ampliar el cliente**

`api.ts` gana `crearCaptura`, `subirFoto`, `actualizarCaptura` y `buscarCarta(setId, localId)`. Las escrituras van por rutas de API de Next (`app/api/...`) o directo contra FastAPI; directo es más simple y el backend ya está en el mismo origen lógico durante desarrollo.

- [ ] **Step 2: La pantalla**

Flujo en una sola pantalla, no un asistente de varios pasos — el requisito son 30 segundos:

1. Botón grande de cámara (`<input type="file" accept="image/*" capture="environment">`).
2. Al elegir foto: se redimensiona en el cliente a 2048 px y 400 px de lado mayor con `canvas`, se genera el `client_draft_id` con `crypto.randomUUID()`, se piden las URLs firmadas y **las dos versiones suben en paralelo**.
3. Mientras suben, el usuario ya puede: escribir el número de colección (ej. `001/165`), tocar el chip de variante, y escribir el precio pagado.
4. Al escribir el número, se consulta `GET /catalog/sets/{set}/{numero}` y aparece la carta encontrada con su arte para confirmar. Es la identificación manual: rápida, exacta y sin API de visión.
5. "Guardar" manda el PATCH final con `capture_status: "listo"`.

Los chips de variante son los del spec §6.2: modernos siempre, vintage solo si el set es WOTC.

- [ ] **Step 3: Estados de subida honestos**

La foto puede seguir subiendo cuando el usuario ya terminó de escribir. El botón de guardar no se bloquea: guarda el ejemplar y la foto se adjunta al terminar. Si la subida falla, el ejemplar queda guardado sin foto y la pantalla lo dice — nunca se pierde el registro por un fallo de red.

- [ ] **Step 4: Verificar en el navegador**

Registrar una carta real de punta a punta y confirmar que el bolsillo correspondiente del binder pasa a color.

---

## Task 5: El binder refleja lo conseguido

**Files:**
- Modify: `frontend/app/binder/Pocket.tsx` (enlace a la ficha)
- Modify: `frontend/app/binder/Rail.tsx`

- [ ] **Step 1:** El contador del riel ya lee `owned_count`; con la Task 2 empieza a moverse solo. Verificar que al registrar una carta pasa de `000` a `001`.
- [ ] **Step 2:** "Completar el 151" deja de sumar los Pokémon ya conseguidos — ese filtro ya existe (`owned_count === 0`), verificar que responde.
- [ ] **Step 3:** Añadir al riel un enlace visible a `/registrar`.

---

## Verificación del plan completo

- [ ] Registrar una carta desde el celular toma menos de 30 segundos
- [ ] El bolsillo pasa de gris a color y el contador sube
- [ ] Reenviar el mismo `client_draft_id` no crea un segundo ejemplar
- [ ] Un ejemplar no puede guardarse con una variante que no es de su carta
- [ ] La foto se sirve con URL firmada; el bucket no es público
- [ ] La suite pasa sin red

## Qué queda fuera

- Identificación automática por visión: necesita una llave de API que no existe en este entorno. `RecognitionPort` queda definido y el adaptador manual cumple el contrato.
- Compras con prorrateo, geolocalización y binder virtual: planes posteriores del spec.
