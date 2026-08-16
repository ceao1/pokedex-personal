# Fundación y catálogo espejo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Levantar el backend y el espejo perezoso del catálogo: pedir una carta a TCGdex por ID o por set+número, guardarla en Supabase con sus variantes y el precio en USD congelado, y servirla por HTTP.

**Architecture:** FastAPI como único cliente de Supabase, con las tablas en el esquema `app` fuera de la Data API. El catálogo se copia bajo demanda: la primera vez que se pide una carta se trae de TCGdex y se hace upsert; después se sirve de la base. SQL plano con psycopg 3 y migraciones gestionadas por el CLI de Supabase — sin ORM y sin un segundo sistema de migraciones.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3, httpx, Pydantic v2, pytest + respx, ruff, uv, Supabase CLI.

**Spec:** `docs/superpowers/specs/2026-08-15-pokedex-viviente-design.md`

## Global Constraints

- **Moneda única USD.** Nunca se lee ni se convierte el bloque `cardmarket` (EUR). Spec D1.
- **Las tablas viven en el esquema `app`, nunca en `public`.** La Data API no debe exponer `app`. Spec D13.
- **RLS habilitada en toda tabla de `app`**, sin políticas para `anon` ni `authenticated`. Spec §4.1.
- **Llaves:** `sb_secret_...` solo en el backend. Nunca `service_role` ni `anon` (nombres legacy, deprecados a fines de 2026). Spec §4.1.
- **Tipos:** `text` en vez de `varchar(n)`; `timestamptz` en vez de `timestamp`; `numeric` para dinero, nunca `float`.
- **Identificadores SQL en minúsculas y sin comillas.**
- **El precio se extrae de la sub-clave de `tcgplayer` que corresponde al `type` de la variante** (`normal` → `normal`, `reverse` → `reverse-holofoil`, `holo` → `holofoil`). Nunca `pricing.tcgplayer.marketPrice` directo: esa clave no existe. Spec §3.
- **Las URLs de imagen de TCGdex necesitan sufijo.** El campo `image` es una base; hay que añadir `/high.png` (o `/low.webp`). Sin sufijo devuelve 404.
- Ningún test de la suite por defecto puede pegarle a la red. Los que sí lo hacen llevan `@pytest.mark.contract` y quedan excluidos por configuración.

---

## Ubicación de este plan en el proyecto

El spec cubre varios subsistemas independientes. Se implementa en seis planes, cada uno con software funcionando al terminar. **Este documento es el plan 1.**

| Plan | Entregable |
|---|---|
| **1. Fundación y catálogo espejo** | Pedir una carta y que quede espejada con su precio |
| 2. Wishlist, checklist e import del Excel | Ver el checklist de los 151 y la wishlist en pantalla |
| 3. Captura móvil y reconocimiento | Registrar una carta con foto de punta a punta |
| 4. Compras y prorrateo | Agrupar ejemplares en compras y repartir el costo |
| 5. Geolocalización y binder | Dónde se compró y dónde está guardada |
| 6. Dashboard y export | Progreso, inversión y volcado de la data |

---

## Estructura de archivos

```
backend/
  pyproject.toml                          # deps, config de pytest y ruff
  .env.example
  src/pokedex/
    config.py                             # settings desde el entorno
    db.py                                 # pool de conexiones
    catalog/
      models.py                           # Card, CardVariant (Pydantic)
      pricing.py                          # extracción del precio USD
      variants.py                         # parseo de variants_detailed
      ports.py                            # protocolo CatalogPort
      tcgdex.py                           # adaptador HTTP
      repository.py                       # upsert y lectura en SQL
      service.py                          # espejo perezoso
    api/
      main.py                             # app FastAPI y lifespan
      routes/catalog.py                   # endpoints del catálogo
  tests/
    conftest.py                           # fixtures de base y pool
    fixtures/
      card_sv03.5-199.json                # Charizard ex: holo con precio
      card_sv03.5-001.json                # Bulbasaur: normal+reverse, stamp set-logo
      card_base1-4.json                   # Charizard Base: variantes vintage sin precio
    catalog/
      test_pricing.py
      test_variants.py
      test_tcgdex.py
      test_tcgdex_contract.py             # marcado contract
      test_repository.py
      test_service.py
    api/
      test_catalog_routes.py
    test_security_data_api.py             # la Data API no expone app
supabase/
  config.toml
  migrations/
    <ts>_create_app_schema.sql
    <ts>_create_card_tables.sql
```

Cada archivo tiene una responsabilidad: `pricing.py` solo sabe sacar un número de un dict, `variants.py` solo sabe aplanar la lista de variantes, `tcgdex.py` solo sabe hablar HTTP, `repository.py` solo sabe SQL, `service.py` solo orquesta. Esa separación es lo que permite testear la parte delicada — la extracción de precios — sin red y sin base.

---

## Task 1: Scaffolding del backend y stack local de Supabase

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.env.example`
- Create: `backend/src/pokedex/__init__.py`
- Create: `backend/src/pokedex/config.py`
- Create: `backend/src/pokedex/api/__init__.py`
- Create: `backend/src/pokedex/api/main.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/api/__init__.py`
- Test: `backend/tests/api/test_health.py`
- Create: `supabase/config.toml` (lo genera `supabase init`)

**Interfaces:**
- Consumes: nada
- Produces: `pokedex.config.Settings` con `database_url: str` y `tcgdex_base_url: str`; `pokedex.api.main.app` (instancia FastAPI)

- [ ] **Step 1: Inicializar el proyecto Python**

```bash
mkdir -p backend/src/pokedex/api backend/tests/api
cd backend
uv init --no-workspace --bare
```

- [ ] **Step 2: Escribir `backend/pyproject.toml`**

```toml
[project]
name = "pokedex"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "httpx>=0.27",
    "psycopg[binary,pool]>=3.2",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
    "ruff>=0.7",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/pokedex"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = ["contract: pega a la API real de TCGdex; excluido por defecto"]
addopts = "-m 'not contract'"

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 3: Instalar dependencias**

```bash
cd backend && uv sync
```

- [ ] **Step 4: Escribir el test de salud (que va a fallar)**

`backend/tests/api/test_health.py`:

```python
from fastapi.testclient import TestClient

from pokedex.api.main import app


def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 5: Correr el test y verificar que falla**

Run: `cd backend && uv run pytest tests/api/test_health.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'pokedex.api.main'`

- [ ] **Step 6: Escribir la configuración**

`backend/src/pokedex/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    tcgdex_base_url: str = "https://api.tcgdex.net/v2/en"


settings = Settings()
```

`backend/.env.example`:

```
# URL de la base local que imprime `supabase status`
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres
TCGDEX_BASE_URL=https://api.tcgdex.net/v2/en
```

- [ ] **Step 7: Escribir la app FastAPI mínima**

`backend/src/pokedex/api/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="Pokédex Viviente")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

Crear también los `__init__.py` vacíos en `src/pokedex/`, `src/pokedex/api/`, `tests/` y `tests/api/`.

- [ ] **Step 8: Correr el test y verificar que pasa**

Run: `cd backend && uv run pytest tests/api/test_health.py -v`
Expected: PASS

- [ ] **Step 9: Levantar Supabase en local**

```bash
cd /Users/carlosanzola/Documents/sandbox/pokedex
supabase init
supabase start
supabase status
```

`supabase status` imprime la URL de la API (por defecto `http://127.0.0.1:54321`), la URL de la base (`postgresql://postgres:postgres@127.0.0.1:54322/postgres`) y las llaves locales. Anotar la llave publicable: la necesita el test de la Task 2.

Si `supabase` no está instalado: `brew install supabase/tap/supabase`. **`supabase start` necesita Docker corriendo** — es el único paso del plan que puede fallar por algo ajeno al código, con un error de conexión al daemon que no dice claramente eso.

- [ ] **Step 10: Verificar que la base responde**

Run: `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -c "select version();"`
Expected: imprime la versión de PostgreSQL

- [ ] **Step 11: Commit**

```bash
cd /Users/carlosanzola/Documents/sandbox/pokedex
git add backend supabase .gitignore
git commit -m "feat: scaffolding del backend FastAPI y stack local de Supabase"
```

---

## Task 2: Esquema `app` cerrado a la Data API

El spec apuesta toda la seguridad a que `app` no esté expuesto (D13). Esta task escribe la migración **y** el test que lo vigila, porque si alguien agrega `app` a la lista de esquemas expuestos nada más lo notaría.

**Files:**
- Create: `supabase/migrations/<ts>_create_app_schema.sql`
- Test: `backend/tests/test_security_data_api.py`
- Modify: `backend/tests/conftest.py` (crear)

**Interfaces:**
- Consumes: `Settings` de la Task 1
- Produces: el esquema `app` en la base; fixture `supabase_api_url` y `supabase_publishable_key` en `conftest.py`

- [ ] **Step 1: Crear el archivo de migración**

```bash
cd /Users/carlosanzola/Documents/sandbox/pokedex
supabase migration new create_app_schema
```

Nunca inventar el nombre del archivo a mano: el comando genera el timestamp correcto.

- [ ] **Step 2: Escribir la migración**

En el archivo recién creado:

```sql
create schema if not exists app;

-- FastAPI se conecta con una llave secreta, que usa el rol service_role.
-- Ese rol salta RLS, así que no hace falta concederle nada explícito.
-- Los roles de la Data API no deben poder ni ver el esquema.
revoke all on schema app from anon, authenticated;
```

- [ ] **Step 3: Aplicar la migración**

```bash
supabase db reset
```

- [ ] **Step 4: Escribir `conftest.py` con los datos del stack local**

`backend/tests/conftest.py`:

```python
import os
import subprocess

import pytest


def _supabase_status() -> dict[str, str]:
    """Lee la salida de `supabase status -o env` como diccionario."""
    result = subprocess.run(
        ["supabase", "status", "-o", "env"],
        capture_output=True,
        text=True,
        check=True,
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
    )
    values = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"')
    return values


@pytest.fixture(scope="session")
def supabase_env() -> dict[str, str]:
    return _supabase_status()


@pytest.fixture(scope="session")
def supabase_api_url(supabase_env: dict[str, str]) -> str:
    return supabase_env["API_URL"]


@pytest.fixture(scope="session")
def supabase_publishable_key(supabase_env: dict[str, str]) -> str:
    return supabase_env["PUBLISHABLE_KEY"]
```

El stack local emite las cuatro llaves: `PUBLISHABLE_KEY` (`sb_publishable_...`) y `SECRET_KEY` (`sb_secret_...`) junto a las legacy `ANON_KEY` y `SERVICE_ROLE_KEY`. Se usa la publicable, coherente con la restricción global sobre nombres de llaves.

- [ ] **Step 5: Escribir el test de exposición (que va a fallar)**

`backend/tests/test_security_data_api.py`:

```python
import httpx


def test_data_api_no_expone_el_esquema_app(supabase_api_url: str, supabase_publishable_key: str):
    """La colección entera queda legible desde el navegador si app se expone."""
    response = httpx.get(
        f"{supabase_api_url}/rest/v1/card",
        params={"select": "*"},
        headers={
            "apikey": supabase_publishable_key,
            "Authorization": f"Bearer {supabase_publishable_key}",
        },
    )
    assert response.status_code >= 400, (
        f"app.card es alcanzable por la Data API: {response.status_code} {response.text}"
    )
```

- [ ] **Step 6: Correr el test**

Run: `cd backend && uv run pytest tests/test_security_data_api.py -v`
Expected: PASS. La tabla no existe todavía, así que PostgREST responde 404. El test se vuelve significativo en la Task 3, cuando la tabla exista y siga sin ser alcanzable.

- [ ] **Step 7: Commit**

```bash
git add supabase/migrations backend/tests
git commit -m "feat: esquema app cerrado a la Data API, con test que lo vigila"
```

---

## Task 3: Tablas `card` y `card_variant`

**Files:**
- Create: `supabase/migrations/<ts>_create_card_tables.sql`
- Test: `backend/tests/catalog/test_schema.py`
- Create: `backend/tests/catalog/__init__.py`

**Interfaces:**
- Consumes: el esquema `app` de la Task 2
- Produces: tablas `app.card` y `app.card_variant`; fixture `db_conn` en `conftest.py`

- [ ] **Step 1: Crear la migración**

```bash
supabase migration new create_card_tables
```

- [ ] **Step 2: Escribir el DDL**

```sql
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
```

Notas sobre las decisiones:
- `id` es texto porque la llave natural es el ID de TCGdex (`sv03.5-199`). No se inventa un subrogado: el ID externo ya es estable y único, y evita un join extra en cada lookup.
- El índice de `card_id` en `card_variant` es obligatorio: Postgres **no** indexa las claves foráneas automáticamente, y sin él cada borrado en cascada hace un seq scan.
- El índice de `dex_number` es parcial porque las cartas de entrenador y energía no tienen dex, y en el set 151 eso es una fracción real de las filas.
- El `check` impide el estado incoherente "hay precio pero no sé de cuándo", que es justo lo que rompería el etiquetado con fecha del dashboard.

- [ ] **Step 3: Aplicar**

```bash
supabase db reset
```

- [ ] **Step 4: Agregar el fixture de conexión a `conftest.py`**

Añadir a `backend/tests/conftest.py`:

```python
import psycopg
from psycopg.rows import dict_row

from pokedex.config import settings


@pytest.fixture()
def db_conn():
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn
        conn.rollback()


@pytest.fixture()
def clean_db(db_conn):
    db_conn.execute("truncate app.card cascade")
    db_conn.commit()
    return db_conn
```

- [ ] **Step 5: Escribir el test del esquema**

`backend/tests/catalog/test_schema.py`:

```python
import psycopg
import pytest


def test_las_tablas_del_catalogo_existen_en_el_esquema_app(db_conn):
    rows = db_conn.execute(
        "select tablename from pg_tables where schemaname = 'app' order by tablename"
    ).fetchall()
    nombres = [r["tablename"] for r in rows]
    assert "card" in nombres
    assert "card_variant" in nombres


def test_rls_habilitada_en_las_tablas_del_catalogo(db_conn):
    rows = db_conn.execute(
        """
        select c.relname, c.relrowsecurity
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'app' and c.relkind = 'r'
        """
    ).fetchall()
    sin_rls = [r["relname"] for r in rows if not r["relrowsecurity"]]
    assert sin_rls == [], f"tablas de app sin RLS: {sin_rls}"


def test_el_precio_y_su_fecha_van_juntos(db_conn):
    # Tras la CheckViolation la transacción queda abortada: no agregar
    # aserciones después del bloque `raises`, fallarían por eso y no por
    # lo que quieran verificar. El fixture hace rollback al terminar.
    db_conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, raw)
        values ('test-1', 'Test', 's', 'S', '1', '{}'::jsonb)
        """
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            """
            insert into app.card_variant (id, card_id, type, price_usd, raw)
            values ('v1', 'test-1', 'normal', 1.00, '{}'::jsonb)
            """
        )
```

- [ ] **Step 6: Correr los tests**

Run: `cd backend && uv run pytest tests/catalog/test_schema.py tests/test_security_data_api.py -v`
Expected: PASS los cuatro. El de la Data API ahora sí es significativo: la tabla existe y sigue sin ser alcanzable.

- [ ] **Step 7: Correr los advisors de Supabase**

```bash
supabase db advisors
```
Expected: sin hallazgos de seguridad. Si reporta alguno, resolverlo antes de commitear.

- [ ] **Step 8: Commit**

```bash
git add supabase/migrations backend/tests
git commit -m "feat: tablas card y card_variant con RLS e índices"
```

---

## Task 4: Grabar los fixtures de payloads reales

Los tests de parseo se apoyan en payloads reales grabados una vez, no en JSON inventado. Los tres elegidos cubren los tres casos que importan.

**Files:**
- Create: `backend/tests/fixtures/card_sv03.5-199.json`
- Create: `backend/tests/fixtures/card_sv03.5-001.json`
- Create: `backend/tests/fixtures/card_base1-4.json`
- Create: `backend/tests/fixtures/__init__.py`
- Create: `backend/tests/catalog/loaders.py`

**Interfaces:**
- Produces: `tests.catalog.loaders.load_fixture(name: str) -> dict`

- [ ] **Step 1: Descargar los tres payloads**

```bash
cd backend/tests/fixtures
curl -s "https://api.tcgdex.net/v2/en/cards/sv03.5-199" -o "card_sv03.5-199.json"
curl -s "https://api.tcgdex.net/v2/en/cards/sv03.5-001" -o "card_sv03.5-001.json"
curl -s "https://api.tcgdex.net/v2/en/cards/base1-4"    -o "card_base1-4.json"
```

Qué cubre cada uno:
- **sv03.5-199** (Charizard ex): una sola variante `holo`, sub-clave `holofoil` con precio.
- **sv03.5-001** (Bulbasaur): variantes `normal` y `reverse` compartiendo el mismo bloque de precios con dos sub-claves, **más** una entrada `normal` con `stamp: ["set-logo"]` y `tcgplayer: null`, y una `reverse` con `foil: "cosmos"`. Es el caso de desambiguación.
- **base1-4** (Charizard Base Set): variantes vintage; la `unlimited` con precio y las `shadowless` / `1st-edition` con `pricing: null`.

- [ ] **Step 2: Verificar que se grabaron bien**

```bash
cd backend/tests/fixtures && for f in *.json; do printf "%s: " "$f"; python3 -c "import json,sys; d=json.load(open('$f')); print(d['id'], d['name'], len(d.get('variants_detailed',[])), 'variantes')"; done
```
Expected: tres líneas con IDs `sv03.5-199`, `sv03.5-001` y `base1-4`.

- [ ] **Step 3: Escribir el cargador**

`backend/tests/catalog/loaders.py`:

```python
import json
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/fixtures backend/tests/catalog/loaders.py
git commit -m "test: grabar payloads reales de TCGdex como fixtures"
```

---

## Task 5: Extracción del precio en USD

La pieza más delicada del plan. Un error aquí asigna a una carta común el precio de su versión con sello — 280 veces más — y envenena el prorrateo y el P&L en silencio.

**Files:**
- Create: `backend/src/pokedex/catalog/__init__.py`
- Create: `backend/src/pokedex/catalog/pricing.py`
- Test: `backend/tests/catalog/test_pricing.py`

**Interfaces:**
- Consumes: `load_fixture` de la Task 4
- Produces: `pokedex.catalog.pricing.extract_price_usd(variant: dict) -> Decimal | None` y la constante `TCGPLAYER_SUBKEY_BY_TYPE: dict[str, str]`

- [ ] **Step 1: Escribir los tests (que van a fallar)**

`backend/tests/catalog/test_pricing.py`:

```python
from decimal import Decimal

from pokedex.catalog.pricing import extract_price_usd

from .loaders import load_fixture

# Se selecciona por variantId y no por atributos: varias entradas comparten
# `type`, así que un filtro por criterios acertaría solo por el orden del
# arreglo. Estos IDs están congelados en los fixtures de la Task 4.
BULBASAUR_NORMAL = "endfynwn4n10gzq"
BULBASAUR_REVERSE = "cm4kqul3x1bwlz1f"
BULBASAUR_NORMAL_SET_LOGO = "3takscxpcqodqyjzqnsbuwq6"
CHARIZARD_EX_HOLO = "jr7oetx1mqug9"
CHARIZARD_BASE_1ST_ED = "mtltux8qtgdu4exu903oasum21juxbvx6lx"


def _variant(card_name: str, variant_id: str) -> dict:
    card = load_fixture(card_name)
    for variant in card["variants_detailed"]:
        if variant.get("variantId") == variant_id:
            return variant
    raise AssertionError(f"{card_name} no tiene la variante {variant_id}")


def test_los_fixtures_tienen_las_variantes_que_los_tests_esperan():
    """Si se regraban los fixtures y TCGdex cambió los variantId, falla aquí
    con un mensaje claro en vez de en cada test de precio."""
    _variant("card_sv03.5-001", BULBASAUR_NORMAL)
    _variant("card_sv03.5-001", BULBASAUR_REVERSE)
    _variant("card_sv03.5-001", BULBASAUR_NORMAL_SET_LOGO)
    _variant("card_sv03.5-199", CHARIZARD_EX_HOLO)
    _variant("card_base1-4", CHARIZARD_BASE_1ST_ED)


def test_holo_lee_la_subclave_holofoil():
    variant = _variant("card_sv03.5-199", CHARIZARD_EX_HOLO)
    assert extract_price_usd(variant) == Decimal("371.66")


def test_normal_lee_la_subclave_normal_y_no_la_de_reverse():
    variant = _variant("card_sv03.5-001", BULBASAUR_NORMAL)
    assert extract_price_usd(variant) == Decimal("0.25")


def test_reverse_lee_la_subclave_reverse_holofoil():
    """Mismo bloque `tcgplayer` que la normal, distinta sub-clave."""
    variant = _variant("card_sv03.5-001", BULBASAUR_REVERSE)
    assert extract_price_usd(variant) == Decimal("0.38")


def test_sin_bloque_tcgplayer_no_hay_precio():
    """La variante con sello tiene precio en Cardmarket pero no en TCGplayer.
    Por la decisión de moneda única no se usa EUR como respaldo."""
    variant = _variant("card_sv03.5-001", BULBASAUR_NORMAL_SET_LOGO)
    assert extract_price_usd(variant) is None


def test_variante_sin_pricing_no_tiene_precio():
    variant = _variant("card_base1-4", CHARIZARD_BASE_1ST_ED)
    assert extract_price_usd(variant) is None


def test_tipo_desconocido_no_revienta():
    assert extract_price_usd({"type": "wPromo", "pricing": {"tcgplayer": {"unit": "USD"}}}) is None


def test_devuelve_decimal_y_no_float():
    variant = _variant("card_sv03.5-001", BULBASAUR_NORMAL)
    assert isinstance(extract_price_usd(variant), Decimal)
```

Los valores esperados (`371.66`, `0.25`, `0.38`) salen de los fixtures grabados en la Task 4. Si un fixture se regraba y los precios cambian, hay que actualizar estas constantes — es intencional: el test verifica el parseo, no el mercado.

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd backend && uv run pytest tests/catalog/test_pricing.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'pokedex.catalog'`

- [ ] **Step 3: Implementar**

`backend/src/pokedex/catalog/pricing.py`:

```python
"""Extracción del precio de mercado en USD desde un payload de TCGdex.

El bloque `pricing` de TCGdex NO está scopeado a la variante: el mismo objeto
`tcgplayer` se repite idéntico en todas las entradas de `variants_detailed`, y
contiene una sub-clave por tipo de acabado. Hay que elegir la sub-clave según
el `type` de la variante; leer `pricing.tcgplayer.marketPrice` directo no
funciona porque esa clave no existe.

Cardmarket viene en EUR y no se usa: la aplicación trabaja en USD y no tiene
tabla de tipo de cambio.
"""

from decimal import Decimal

TCGPLAYER_SUBKEY_BY_TYPE = {
    "normal": "normal",
    "reverse": "reverse-holofoil",
    "holo": "holofoil",
}


def extract_price_usd(variant: dict) -> Decimal | None:
    """Precio de mercado en USD de una entrada de `variants_detailed`.

    Devuelve None cuando no hay precio disponible, que es un estado válido
    y frecuente en variantes vintage.
    """
    pricing = variant.get("pricing") or {}
    tcgplayer = pricing.get("tcgplayer") or {}

    subkey = TCGPLAYER_SUBKEY_BY_TYPE.get(variant.get("type", ""))
    if subkey is None:
        return None

    block = tcgplayer.get(subkey)
    if not isinstance(block, dict):
        return None

    market_price = block.get("marketPrice")
    if market_price is None:
        return None

    return Decimal(str(market_price))
```

`Decimal(str(...))` y no `Decimal(...)` sobre el float: convertir directo arrastra el error binario del float y `0.38` se vuelve `0.3799999...`.

Crear también `backend/src/pokedex/catalog/__init__.py` vacío.

- [ ] **Step 4: Correr y verificar que pasan**

Run: `cd backend && uv run pytest tests/catalog/test_pricing.py -v`
Expected: los 7 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/pokedex/catalog backend/tests/catalog/test_pricing.py
git commit -m "feat: extracción del precio USD por sub-clave de tcgplayer"
```

---

## Task 6: Parseo de variantes y desambiguación

**Files:**
- Create: `backend/src/pokedex/catalog/models.py`
- Create: `backend/src/pokedex/catalog/variants.py`
- Test: `backend/tests/catalog/test_variants.py`

**Interfaces:**
- Consumes: `extract_price_usd` de la Task 5
- Produces:
  - `pokedex.catalog.models.CardVariant` (Pydantic) con campos `id, type, subtype, stamp, foil, size, price_usd, price_captured_at, raw`
  - `pokedex.catalog.models.Card` con `id, name, set_id, set_name, local_id, set_card_count, rarity, image_url, dex_number, raw, variants: list[CardVariant]`
  - `pokedex.catalog.variants.parse_variants(payload: dict, captured_at: datetime) -> list[CardVariant]`
  - `pokedex.catalog.variants.pick_variant(variants: list[CardVariant], label: str) -> CardVariant | None`
  - `pokedex.catalog.variants.VariantLabel` (enum de str): `NORMAL, REVERSE, HOLO, FIRST_EDITION, SHADOWLESS, UNLIMITED`

- [ ] **Step 1: Escribir los tests (que van a fallar)**

`backend/tests/catalog/test_variants.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal

from pokedex.catalog.variants import VariantLabel, parse_variants, pick_variant

from .loaders import load_fixture

CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def test_parsea_todas_las_variantes_del_payload():
    variants = parse_variants(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    assert len(variants) == len(load_fixture("card_sv03.5-001")["variants_detailed"])
    assert all(v.id for v in variants)


def test_asigna_precio_y_fecha_juntos():
    variants = parse_variants(load_fixture("card_sv03.5-199"), CAPTURED_AT)
    holo = variants[0]
    assert holo.price_usd == Decimal("371.66")
    assert holo.price_captured_at == CAPTURED_AT


def test_sin_precio_tampoco_hay_fecha():
    """El check de la base exige que precio y fecha vayan juntos."""
    variants = parse_variants(load_fixture("card_base1-4"), CAPTURED_AT)
    sin_precio = [v for v in variants if v.price_usd is None]
    assert sin_precio, "el fixture debe tener variantes sin precio"
    assert all(v.price_captured_at is None for v in sin_precio)


def test_pick_normal_prefiere_la_entrada_sin_sello():
    """Bulbasaur tiene dos entradas normal; la del sello vale 280 veces más."""
    variants = parse_variants(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    elegida = pick_variant(variants, VariantLabel.NORMAL)
    assert elegida is not None
    assert elegida.stamp == []
    assert elegida.price_usd == Decimal("0.25")


def test_pick_reverse_prefiere_la_entrada_sin_foil():
    variants = parse_variants(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    elegida = pick_variant(variants, VariantLabel.REVERSE)
    assert elegida is not None
    assert elegida.foil is None
    assert elegida.price_usd == Decimal("0.38")


def test_pick_first_edition_en_vintage():
    variants = parse_variants(load_fixture("card_base1-4"), CAPTURED_AT)
    elegida = pick_variant(variants, VariantLabel.FIRST_EDITION)
    assert elegida is not None
    assert "1st-edition" in elegida.stamp


def test_pick_shadowless_excluye_la_de_primera_edicion():
    variants = parse_variants(load_fixture("card_base1-4"), CAPTURED_AT)
    elegida = pick_variant(variants, VariantLabel.SHADOWLESS)
    assert elegida is not None
    assert elegida.subtype == "shadowless"
    assert "1st-edition" not in elegida.stamp


def test_pick_devuelve_none_si_no_hay_coincidencia():
    variants = parse_variants(load_fixture("card_sv03.5-199"), CAPTURED_AT)
    assert pick_variant(variants, VariantLabel.SHADOWLESS) is None


def test_el_chip_moderno_de_holo_no_matchea_vintage():
    """Todas las holo de Base Set tienen subtype, así que el chip Holo no
    aplica. Es la otra mitad de la exclusividad de grupos del spec §6.2:
    sin este test, aflojar _matches pasaría inadvertido."""
    variants = parse_variants(load_fixture("card_base1-4"), CAPTURED_AT)
    assert pick_variant(variants, VariantLabel.HOLO) is None
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd backend && uv run pytest tests/catalog/test_variants.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'pokedex.catalog.variants'`

- [ ] **Step 3: Escribir los modelos**

`backend/src/pokedex/catalog/models.py`:

```python
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CardVariant(BaseModel):
    id: str
    type: str
    subtype: str | None = None
    stamp: list[str] = Field(default_factory=list)
    foil: str | None = None
    size: str | None = None
    price_usd: Decimal | None = None
    price_captured_at: datetime | None = None
    raw: dict


class Card(BaseModel):
    id: str
    name: str
    set_id: str
    set_name: str
    local_id: str
    set_card_count: int | None = None
    rarity: str | None = None
    image_url: str | None = None
    dex_number: int | None = None
    raw: dict
    variants: list[CardVariant] = Field(default_factory=list)
```

- [ ] **Step 4: Escribir el parseo y la desambiguación**

`backend/src/pokedex/catalog/variants.py`:

```python
"""Parseo de `variants_detailed` y elección de la variante que el usuario marcó.

Una carta puede tener varias entradas del mismo `type`, distinguidas por
`stamp` (ej. `set-logo`) o `foil` (ej. `cosmos`). Son cartas distintas con
precios muy distintos, así que la desambiguación importa: en Bulbasaur
sv03.5-001 la entrada con sello cuesta 280 veces más que la común.
"""

from datetime import datetime
from enum import StrEnum

from .models import CardVariant
from .pricing import extract_price_usd


class VariantLabel(StrEnum):
    NORMAL = "normal"
    REVERSE = "reverse"
    HOLO = "holo"
    FIRST_EDITION = "first_edition"
    SHADOWLESS = "shadowless"
    UNLIMITED = "unlimited"


def parse_variants(payload: dict, captured_at: datetime) -> list[CardVariant]:
    variants: list[CardVariant] = []
    for entry in payload.get("variants_detailed", []):
        price = extract_price_usd(entry)
        variants.append(
            CardVariant(
                id=entry["variantId"],
                type=entry["type"],
                subtype=entry.get("subtype"),
                stamp=entry.get("stamp") or [],
                foil=entry.get("foil"),
                size=entry.get("size"),
                price_usd=price,
                # El check de la base exige que ambos sean nulos o ninguno.
                price_captured_at=captured_at if price is not None else None,
                raw=entry,
            )
        )
    return variants


def _matches(variant: CardVariant, label: VariantLabel) -> bool:
    match label:
        case VariantLabel.NORMAL:
            return variant.type == "normal"
        case VariantLabel.REVERSE:
            return variant.type == "reverse"
        case VariantLabel.HOLO:
            return variant.type == "holo" and variant.subtype is None
        case VariantLabel.FIRST_EDITION:
            return "1st-edition" in variant.stamp
        case VariantLabel.SHADOWLESS:
            return variant.subtype == "shadowless" and "1st-edition" not in variant.stamp
        case VariantLabel.UNLIMITED:
            return variant.subtype == "unlimited"
    return False


def _specificity(variant: CardVariant) -> tuple[int, int, int]:
    """Menor es más preferible: sin sello, sin foil, tamaño estándar."""
    return (
        1 if variant.stamp else 0,
        1 if variant.foil else 0,
        0 if variant.size in (None, "standard") else 1,
    )


def pick_variant(variants: list[CardVariant], label: VariantLabel) -> CardVariant | None:
    """La variante que corresponde al chip que tocó el usuario.

    Si quedan varias candidatas, gana la menos exótica. Cuando ni así se
    desempata, el llamador debe mandar el ejemplar a revisión manual.
    """
    candidatas = [v for v in variants if _matches(v, label)]
    if not candidatas:
        return None
    return min(candidatas, key=_specificity)
```

`FIRST_EDITION` se evalúa por `stamp` y no por `type`, y va antes que `SHADOWLESS` en la intención del usuario: en Base Set la carta de primera edición **también** es shadowless, así que el chip de shadowless excluye explícitamente el sello para que los dos chips no devuelvan la misma fila.

- [ ] **Step 5: Correr y verificar que pasan**

Run: `cd backend && uv run pytest tests/catalog/test_variants.py -v`
Expected: los 8 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/pokedex/catalog backend/tests/catalog/test_variants.py
git commit -m "feat: parseo de variantes con desambiguación por sello y foil"
```

---

## Task 7: Adaptador de TCGdex

**Files:**
- Create: `backend/src/pokedex/catalog/ports.py`
- Create: `backend/src/pokedex/catalog/tcgdex.py`
- Test: `backend/tests/catalog/test_tcgdex.py`

**Interfaces:**
- Consumes: `Card`, `CardVariant`, `parse_variants` de la Task 6; `Settings` de la Task 1
- Produces:
  - `pokedex.catalog.ports.CatalogPort` (Protocol) con `async get_card(card_id: str) -> Card | None` y `async find_by_set_and_number(set_id: str, local_id: str) -> Card | None`
  - `pokedex.catalog.tcgdex.TcgdexCatalog(base_url: str, client: httpx.AsyncClient)` que lo implementa
  - `pokedex.catalog.tcgdex.parse_card(payload: dict, captured_at: datetime) -> Card`
  - `pokedex.catalog.tcgdex.build_image_url(base: str | None, quality: str = "high", extension: str = "png") -> str | None`

- [ ] **Step 1: Escribir los tests (que van a fallar)**

`backend/tests/catalog/test_tcgdex.py`:

```python
from datetime import UTC, datetime

import httpx
import pytest
import respx

from pokedex.catalog.tcgdex import TcgdexCatalog, build_image_url, parse_card

from .loaders import load_fixture

BASE_URL = "https://api.tcgdex.example/v2/en"
CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def test_build_image_url_agrega_el_sufijo():
    """El campo `image` de TCGdex es una base sin extensión; sin sufijo da 404."""
    url = build_image_url("https://assets.tcgdex.net/en/sv/sv03.5/199")
    assert url == "https://assets.tcgdex.net/en/sv/sv03.5/199/high.png"


def test_build_image_url_tolera_ausencia():
    assert build_image_url(None) is None


def test_parse_card_extrae_los_campos_del_catalogo():
    card = parse_card(load_fixture("card_sv03.5-199"), CAPTURED_AT)
    assert card.id == "sv03.5-199"
    assert card.name == "Charizard ex"
    assert card.set_id == "sv03.5"
    assert card.set_name == "151"
    assert card.local_id == "199"
    assert card.set_card_count == 165
    assert card.rarity == "Special illustration rare"
    assert card.dex_number == 6
    assert card.image_url.endswith("/high.png")
    assert len(card.variants) == 1


def test_parse_card_sin_dex_id():
    """Entrenadores y energías no tienen dexId."""
    payload = dict(load_fixture("card_sv03.5-199"))
    payload.pop("dexId")
    assert parse_card(payload, CAPTURED_AT).dex_number is None


@respx.mock
async def test_get_card_pide_el_endpoint_correcto():
    route = respx.get(f"{BASE_URL}/cards/sv03.5-199").mock(
        return_value=httpx.Response(200, json=load_fixture("card_sv03.5-199"))
    )
    async with httpx.AsyncClient() as client:
        catalog = TcgdexCatalog(BASE_URL, client)
        card = await catalog.get_card("sv03.5-199")
    assert route.called
    assert card.id == "sv03.5-199"


@respx.mock
async def test_get_card_devuelve_none_si_no_existe():
    respx.get(f"{BASE_URL}/cards/no-existe").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        catalog = TcgdexCatalog(BASE_URL, client)
        assert await catalog.get_card("no-existe") is None


@respx.mock
async def test_find_by_set_and_number_usa_el_endpoint_de_sets():
    route = respx.get(f"{BASE_URL}/sets/sv03.5/001").mock(
        return_value=httpx.Response(200, json=load_fixture("card_sv03.5-001"))
    )
    async with httpx.AsyncClient() as client:
        catalog = TcgdexCatalog(BASE_URL, client)
        card = await catalog.find_by_set_and_number("sv03.5", "001")
    assert route.called
    assert card.id == "sv03.5-001"


@respx.mock
async def test_un_error_del_servidor_se_propaga():
    respx.get(f"{BASE_URL}/cards/x").mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as client:
        catalog = TcgdexCatalog(BASE_URL, client)
        with pytest.raises(httpx.HTTPStatusError):
            await catalog.get_card("x")
```

Un 404 significa "esa carta no existe" y devuelve `None`; un 500 significa "TCGdex está mal" y debe propagarse, porque el servicio tiene que distinguir "no la encontré" de "no pude preguntar".

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd backend && uv run pytest tests/catalog/test_tcgdex.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'pokedex.catalog.tcgdex'`

- [ ] **Step 3: Escribir el puerto**

`backend/src/pokedex/catalog/ports.py`:

```python
from typing import Protocol

from .models import Card


class CatalogPort(Protocol):
    """Fuente del catálogo de cartas. Intercambiable por diseño (spec §4.3)."""

    async def get_card(self, card_id: str) -> Card | None: ...

    async def find_by_set_and_number(self, set_id: str, local_id: str) -> Card | None: ...
```

- [ ] **Step 4: Escribir el adaptador**

`backend/src/pokedex/catalog/tcgdex.py`:

```python
from datetime import UTC, datetime

import httpx

from .models import Card
from .variants import parse_variants


def build_image_url(base: str | None, quality: str = "high", extension: str = "png") -> str | None:
    """TCGdex devuelve `image` como URL base sin extensión.

    Pedirla tal cual devuelve 404: hay que añadir `/{calidad}.{extensión}`.
    """
    if not base:
        return None
    return f"{base}/{quality}.{extension}"


def parse_card(payload: dict, captured_at: datetime) -> Card:
    card_set = payload.get("set") or {}
    dex_ids = payload.get("dexId") or []
    return Card(
        id=payload["id"],
        name=payload["name"],
        set_id=card_set.get("id", ""),
        set_name=card_set.get("name", ""),
        local_id=payload["localId"],
        set_card_count=(card_set.get("cardCount") or {}).get("official"),
        rarity=payload.get("rarity"),
        image_url=build_image_url(payload.get("image")),
        dex_number=dex_ids[0] if dex_ids else None,
        raw=payload,
        variants=parse_variants(payload, captured_at),
    )


class TcgdexCatalog:
    """Adaptador HTTP de la API pública de TCGdex."""

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def get_card(self, card_id: str) -> Card | None:
        return await self._fetch(f"{self._base_url}/cards/{card_id}")

    async def find_by_set_and_number(self, set_id: str, local_id: str) -> Card | None:
        return await self._fetch(f"{self._base_url}/sets/{set_id}/{local_id}")

    async def _fetch(self, url: str) -> Card | None:
        response = await self._client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return parse_card(response.json(), datetime.now(UTC))
```

- [ ] **Step 5: Correr y verificar que pasan**

Run: `cd backend && uv run pytest tests/catalog/test_tcgdex.py -v`
Expected: los 8 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/pokedex/catalog backend/tests/catalog/test_tcgdex.py
git commit -m "feat: adaptador de TCGdex con CatalogPort"
```

---

## Task 8: Test de contrato contra la API real

Todo el modelo de precios descansa en la forma del payload de TCGdex, que es una dependencia externa que puede cambiar sin avisar. Este test es la alarma.

**Files:**
- Test: `backend/tests/catalog/test_tcgdex_contract.py`

**Interfaces:**
- Consumes: `TcgdexCatalog`, `TCGPLAYER_SUBKEY_BY_TYPE`

- [ ] **Step 1: Escribir el test de contrato**

`backend/tests/catalog/test_tcgdex_contract.py`:

```python
"""Verifica que la API real de TCGdex sigue teniendo la forma que asumimos.

Excluido de la suite por defecto (marca `contract`). Correr a mano:
    uv run pytest -m contract -v
"""

import httpx
import pytest

from pokedex.catalog.pricing import TCGPLAYER_SUBKEY_BY_TYPE
from pokedex.catalog.tcgdex import TcgdexCatalog

pytestmark = pytest.mark.contract

BASE_URL = "https://api.tcgdex.net/v2/en"


async def _get(card_id: str):
    async with httpx.AsyncClient(timeout=20) as client:
        return await TcgdexCatalog(BASE_URL, client).get_card(card_id)


async def test_el_payload_sigue_trayendo_variantes_con_id():
    card = await _get("sv03.5-001")
    assert card is not None
    assert card.variants, "variants_detailed desapareció del payload"
    assert all(v.id for v in card.variants), "las variantes perdieron variantId"


async def test_al_menos_una_variante_moderna_sigue_teniendo_precio():
    card = await _get("sv03.5-001")
    con_precio = [v for v in card.variants if v.price_usd is not None]
    assert con_precio, (
        "ninguna variante trajo precio: o TCGdex dejó de exponer pricing, "
        "o cambiaron las sub-claves de tcgplayer"
    )


async def test_las_subclaves_de_tcgplayer_siguen_llamandose_igual():
    card = await _get("sv03.5-001")
    vistas = set()
    for variant in card.variants:
        block = (variant.raw.get("pricing") or {}).get("tcgplayer") or {}
        vistas.update(k for k in block if k not in {"unit", "updated"})
    conocidas = set(TCGPLAYER_SUBKEY_BY_TYPE.values())
    assert vistas & conocidas, f"sub-claves desconocidas: {vistas}"


async def test_la_url_de_imagen_construida_responde_200():
    card = await _get("sv03.5-199")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.head(card.image_url)
    assert response.status_code == 200, f"{card.image_url} devolvió {response.status_code}"


async def test_una_carta_inexistente_devuelve_none():
    assert await _get("set-que-no-existe-999") is None
```

- [ ] **Step 2: Correr el test de contrato**

Run: `cd backend && uv run pytest -m contract -v`
Expected: los 5 PASS (requiere red)

- [ ] **Step 3: Verificar que la suite por defecto NO lo corre**

Run: `cd backend && uv run pytest -v`
Expected: los tests de contrato aparecen como deseleccionados, no ejecutados

- [ ] **Step 4: Commit**

```bash
git add backend/tests/catalog/test_tcgdex_contract.py
git commit -m "test: contrato contra la API real de TCGdex"
```

---

## Task 9: Repositorio del catálogo

**Files:**
- Create: `backend/src/pokedex/db.py`
- Create: `backend/src/pokedex/catalog/repository.py`
- Test: `backend/tests/catalog/test_repository.py`

**Interfaces:**
- Consumes: `Card`, `CardVariant` de la Task 6; `settings` de la Task 1
- Produces:
  - `pokedex.db.create_pool() -> psycopg_pool.ConnectionPool`
  - `pokedex.catalog.repository.upsert_card(conn, card: Card) -> None`
  - `pokedex.catalog.repository.get_card(conn, card_id: str) -> Card | None`
  - `pokedex.catalog.repository.find_by_set_and_number(conn, set_id: str, local_id: str) -> Card | None`

- [ ] **Step 1: Escribir los tests (que van a fallar)**

`backend/tests/catalog/test_repository.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal

from pokedex.catalog import repository
from pokedex.catalog.tcgdex import parse_card

from .loaders import load_fixture

CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def test_upsert_guarda_la_carta_y_sus_variantes(clean_db):
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    repository.upsert_card(clean_db, card)

    recuperada = repository.get_card(clean_db, "sv03.5-001")
    assert recuperada is not None
    assert recuperada.name == "Bulbasaur"
    assert recuperada.dex_number == 1
    assert len(recuperada.variants) == len(card.variants)


def test_upsert_conserva_el_precio_por_variante(clean_db):
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    repository.upsert_card(clean_db, card)

    recuperada = repository.get_card(clean_db, "sv03.5-001")
    por_id = {v.id: v for v in recuperada.variants}
    original = {v.id: v for v in card.variants}
    for variant_id, esperada in original.items():
        assert por_id[variant_id].price_usd == esperada.price_usd


def test_upsert_es_idempotente(clean_db):
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    repository.upsert_card(clean_db, card)
    repository.upsert_card(clean_db, card)

    total = clean_db.execute(
        "select count(*) as n from app.card_variant where card_id = 'sv03.5-001'"
    ).fetchone()["n"]
    assert total == len(card.variants)


def test_upsert_actualiza_el_precio_al_refrescar(clean_db):
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    repository.upsert_card(clean_db, card)

    con_precio = next(v for v in card.variants if v.price_usd is not None)
    con_precio.price_usd = Decimal("9.99")
    repository.upsert_card(clean_db, card)

    recuperada = repository.get_card(clean_db, "sv03.5-001")
    actualizada = next(v for v in recuperada.variants if v.id == con_precio.id)
    assert actualizada.price_usd == Decimal("9.99")


def test_get_card_devuelve_none_si_no_esta(clean_db):
    assert repository.get_card(clean_db, "no-existe") is None


def test_find_by_set_and_number(clean_db):
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    repository.upsert_card(clean_db, card)

    encontrada = repository.find_by_set_and_number(clean_db, "sv03.5", "001")
    assert encontrada is not None
    assert encontrada.id == "sv03.5-001"
    assert repository.find_by_set_and_number(clean_db, "sv03.5", "999") is None
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd backend && uv run pytest tests/catalog/test_repository.py -v`
Expected: FAIL con `ImportError: cannot import name 'repository'`

- [ ] **Step 3: Escribir el pool de conexiones**

`backend/src/pokedex/db.py`:

```python
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings


def create_pool() -> ConnectionPool:
    """Un solo usuario y un solo proceso web: un pool chico basta.

    Es una factoría y no un pool de módulo a propósito: `ConnectionPool` no se
    puede reabrir después de cerrarlo, y `TestClient` levanta y baja el
    lifespan una vez por test. Un pool global reventaría en el segundo test.
    """
    return ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row},
        open=False,
    )
```

- [ ] **Step 4: Escribir el repositorio**

`backend/src/pokedex/catalog/repository.py`:

```python
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
on conflict (id) do update set
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
```

- [ ] **Step 5: Correr y verificar que pasan**

Run: `cd backend && uv run pytest tests/catalog/test_repository.py -v`
Expected: los 6 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/pokedex/db.py backend/src/pokedex/catalog/repository.py backend/tests/catalog/test_repository.py
git commit -m "feat: repositorio del catálogo con upsert idempotente"
```

---

## Task 10: Servicio de espejo perezoso y endpoints

Cierra el plan: la primera consulta trae la carta de TCGdex y la guarda; las siguientes salen de la base sin tocar la red.

**Files:**
- Create: `backend/src/pokedex/catalog/service.py`
- Create: `backend/src/pokedex/api/routes/__init__.py`
- Create: `backend/src/pokedex/api/routes/catalog.py`
- Modify: `backend/src/pokedex/api/main.py`
- Test: `backend/tests/catalog/test_service.py`
- Test: `backend/tests/api/test_catalog_routes.py`

**Interfaces:**
- Consumes: `CatalogPort` (Task 7), `repository` (Task 9), `pool` (Task 9)
- Produces:
  - `pokedex.catalog.service.CatalogService(catalog: CatalogPort, conn_factory)` con `async get_card(card_id) -> Card | None` y `async find_by_set_and_number(set_id, local_id) -> Card | None`
  - Rutas `GET /catalog/cards/{card_id}` y `GET /catalog/sets/{set_id}/{local_id}`

- [ ] **Step 1: Escribir los tests del servicio (que van a fallar)**

`backend/tests/catalog/test_service.py`:

```python
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import parse_card

from .loaders import load_fixture

CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


class FakeCatalog:
    """Fake del CatalogPort que cuenta las llamadas."""

    def __init__(self, cards: dict):
        self._cards = cards
        self.get_card_calls = 0
        self.find_calls = 0

    async def get_card(self, card_id: str):
        self.get_card_calls += 1
        return self._cards.get(card_id)

    async def find_by_set_and_number(self, set_id: str, local_id: str):
        self.find_calls += 1
        for card in self._cards.values():
            if card.set_id == set_id and card.local_id == local_id:
                return card
        return None


@pytest.fixture()
def conn_factory(clean_db):
    @contextmanager
    def factory():
        yield clean_db

    return factory


@pytest.fixture()
def bulbasaur():
    return parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)


async def test_la_primera_consulta_trae_de_tcgdex_y_espeja(conn_factory, bulbasaur, clean_db):
    fake = FakeCatalog({"sv03.5-001": bulbasaur})
    service = CatalogService(fake, conn_factory)

    card = await service.get_card("sv03.5-001")

    assert card.name == "Bulbasaur"
    assert fake.get_card_calls == 1
    guardadas = clean_db.execute("select count(*) as n from app.card").fetchone()["n"]
    assert guardadas == 1


async def test_la_segunda_consulta_no_toca_la_red(conn_factory, bulbasaur):
    fake = FakeCatalog({"sv03.5-001": bulbasaur})
    service = CatalogService(fake, conn_factory)

    await service.get_card("sv03.5-001")
    card = await service.get_card("sv03.5-001")

    assert card.name == "Bulbasaur"
    assert fake.get_card_calls == 1, "el espejo no evitó la segunda llamada"


async def test_una_carta_inexistente_devuelve_none(conn_factory):
    service = CatalogService(FakeCatalog({}), conn_factory)
    assert await service.get_card("no-existe") is None


async def test_find_by_set_and_number_tambien_espeja(conn_factory, bulbasaur, clean_db):
    fake = FakeCatalog({"sv03.5-001": bulbasaur})
    service = CatalogService(fake, conn_factory)

    await service.find_by_set_and_number("sv03.5", "001")
    card = await service.find_by_set_and_number("sv03.5", "001")

    assert card.id == "sv03.5-001"
    assert fake.find_calls == 1
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd backend && uv run pytest tests/catalog/test_service.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'pokedex.catalog.service'`

- [ ] **Step 3: Escribir el servicio**

`backend/src/pokedex/catalog/service.py`:

```python
"""Espejo perezoso del catálogo.

La primera vez que se pide una carta se trae de TCGdex y se copia a la base
con el precio del momento; a partir de ahí se sirve local. Esto es lo que el
spec llama espejo perezoso (D7): el cache ES el espejo, así que no hace falta
self-hostear el catálogo completo.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager

from psycopg import Connection

from . import repository
from .models import Card
from .ports import CatalogPort

# `pool.connection` cumple esta firma tal cual.
ConnFactory = Callable[[], AbstractContextManager[Connection]]


class CatalogService:
    def __init__(self, catalog: CatalogPort, conn_factory: ConnFactory) -> None:
        self._catalog = catalog
        self._conn_factory = conn_factory

    async def get_card(self, card_id: str) -> Card | None:
        with self._conn_factory() as conn:
            local = repository.get_card(conn, card_id)
            if local is not None:
                return local

        remote = await self._catalog.get_card(card_id)
        if remote is None:
            return None

        with self._conn_factory() as conn:
            repository.upsert_card(conn, remote)
        return remote

    async def find_by_set_and_number(self, set_id: str, local_id: str) -> Card | None:
        with self._conn_factory() as conn:
            local = repository.find_by_set_and_number(conn, set_id, local_id)
            if local is not None:
                return local

        remote = await self._catalog.find_by_set_and_number(set_id, local_id)
        if remote is None:
            return None

        with self._conn_factory() as conn:
            repository.upsert_card(conn, remote)
        return remote
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `cd backend && uv run pytest tests/catalog/test_service.py -v`
Expected: los 4 PASS

- [ ] **Step 5: Escribir los tests de las rutas (que van a fallar)**

`backend/tests/api/test_catalog_routes.py`:

```python
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from pokedex.api.main import app
from pokedex.api.routes.catalog import get_service
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import parse_card

from ..catalog.loaders import load_fixture

CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.fixture()
def client(clean_db):
    """Cliente con el servicio sustituido por un catálogo falso.

    Estos tests verifican ruteo y serialización, no la integración con
    TCGdex; esa la cubren el test de contrato y la prueba manual del
    Step 11. Sustituir la dependencia mantiene la suite offline, que es
    una restricción global de este plan.
    """
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)

    class FakeCatalog:
        async def get_card(self, card_id: str):
            return card if card_id == card.id else None

        async def find_by_set_and_number(self, set_id: str, local_id: str):
            return card if (set_id, local_id) == (card.set_id, card.local_id) else None

    @contextmanager
    def conn_factory():
        yield clean_db

    app.dependency_overrides[get_service] = lambda: CatalogService(FakeCatalog(), conn_factory)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_get_card_devuelve_la_ficha(client):
    response = client.get("/catalog/cards/sv03.5-001")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "sv03.5-001"
    assert body["name"] == "Bulbasaur"
    assert body["image_url"].endswith("/high.png")
    assert len(body["variants"]) >= 1


def test_get_card_inexistente_devuelve_404(client):
    response = client.get("/catalog/cards/set-que-no-existe-999")
    assert response.status_code == 404


def test_get_por_set_y_numero(client):
    response = client.get("/catalog/sets/sv03.5/001")
    assert response.status_code == 200
    assert response.json()["id"] == "sv03.5-001"


def test_la_ficha_no_expone_el_payload_crudo(client):
    """`raw` es detalle de implementación; no se sirve por HTTP."""
    body = client.get("/catalog/cards/sv03.5-001").json()
    assert "raw" not in body


def test_los_precios_llegan_por_variante(client):
    variantes = {v["id"]: v for v in client.get("/catalog/cards/sv03.5-001").json()["variants"]}
    assert variantes["endfynwn4n10gzq"]["price_usd"] == 0.25
    assert variantes["cm4kqul3x1bwlz1f"]["price_usd"] == 0.38
    assert variantes["3takscxpcqodqyjzqnsbuwq6"]["price_usd"] is None
```

Ningún test pega a la red: el catálogo está sustituido por un fake y el espejo escribe en la base local.

- [ ] **Step 6: Correr y verificar que fallan**

Run: `cd backend && uv run pytest tests/api/test_catalog_routes.py -v`
Expected: FAIL con 404 en todas, porque las rutas no existen

- [ ] **Step 7: Escribir las rutas**

`backend/src/pokedex/api/routes/catalog.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pokedex.catalog.models import Card
from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import TcgdexCatalog
from pokedex.config import settings

router = APIRouter(prefix="/catalog", tags=["catalog"])


class VariantOut(BaseModel):
    id: str
    type: str
    subtype: str | None
    stamp: list[str]
    foil: str | None
    price_usd: float | None
    price_captured_at: str | None


class CardOut(BaseModel):
    id: str
    name: str
    set_id: str
    set_name: str
    local_id: str
    set_card_count: int | None
    rarity: str | None
    image_url: str | None
    dex_number: int | None
    variants: list[VariantOut]

    @classmethod
    def from_card(cls, card: Card) -> "CardOut":
        return cls(
            **card.model_dump(exclude={"raw", "variants"}),
            variants=[
                VariantOut(
                    id=v.id,
                    type=v.type,
                    subtype=v.subtype,
                    stamp=v.stamp,
                    foil=v.foil,
                    price_usd=float(v.price_usd) if v.price_usd is not None else None,
                    price_captured_at=(
                        v.price_captured_at.isoformat() if v.price_captured_at else None
                    ),
                )
                for v in card.variants
            ],
        )


def get_service(request: Request) -> CatalogService:
    """El pool y el cliente HTTP viven en app.state, creados en el lifespan.

    Crear un httpx.AsyncClient por request lo dejaría sin cerrar y filtraría
    conexiones; crear el pool al importar impediría reabrirlo entre tests.
    """
    return CatalogService(
        TcgdexCatalog(settings.tcgdex_base_url, request.app.state.http_client),
        request.app.state.pool.connection,
    )


ServiceDep = Annotated[CatalogService, Depends(get_service)]


@router.get("/cards/{card_id}", response_model=CardOut)
async def get_card(card_id: str, service: ServiceDep) -> CardOut:
    card = await service.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"carta {card_id} no encontrada")
    return CardOut.from_card(card)


@router.get("/sets/{set_id}/{local_id}", response_model=CardOut)
async def get_card_by_number(set_id: str, local_id: str, service: ServiceDep) -> CardOut:
    card = await service.find_by_set_and_number(set_id, local_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"carta {set_id}-{local_id} no encontrada")
    return CardOut.from_card(card)
```

`CardOut` existe para no filtrar `raw` por HTTP: el payload crudo pesa y es detalle interno.

- [ ] **Step 8: Conectar las rutas y abrir el pool en el lifespan**

`backend/src/pokedex/api/main.py`:

```python
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from pokedex.api.routes import catalog
from pokedex.db import create_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = create_pool()
    pool.open()
    pool.wait()
    app.state.pool = pool
    app.state.http_client = httpx.AsyncClient(timeout=20)
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        pool.close()


app = FastAPI(title="Pokédex Viviente", lifespan=lifespan)
app.include_router(catalog.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

Crear también `backend/src/pokedex/api/routes/__init__.py` vacío.

- [ ] **Step 9: Correr y verificar que pasan**

Run: `cd backend && uv run pytest tests/api/test_catalog_routes.py -v`
Expected: los 4 PASS

- [ ] **Step 10: Correr la suite completa**

Run: `cd backend && uv run pytest -v && uv run ruff check . && uv run ruff format --check .`
Expected: todo PASS, sin hallazgos de lint

- [ ] **Step 11: Prueba manual de punta a punta**

```bash
cd backend && uv run uvicorn pokedex.api.main:app --reload
```

En otra terminal:

```bash
curl -s localhost:8000/catalog/cards/base1-4 | python3 -m json.tool | head -30
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" \
  -c "select c.name, v.type, v.subtype, v.price_usd from app.card c join app.card_variant v on v.card_id = c.id where c.id = 'base1-4' order by v.price_usd desc nulls last;"
```

Expected: la primera llamada trae Charizard de Base Set y la consulta SQL muestra sus cuatro variantes, con precio solo en la `unlimited`.

- [ ] **Step 12: Commit**

```bash
git add backend
git commit -m "feat: servicio de espejo perezoso y endpoints del catálogo"
```

---

## Verificación del plan completo

Al terminar las diez tasks debe cumplirse:

- [ ] `uv run pytest` pasa entero **sin red** (verificable desconectando el wifi)
- [ ] `uv run pytest -m contract` pasa contra la API real
- [ ] `supabase db advisors` no reporta hallazgos de seguridad
- [ ] `GET /catalog/cards/sv03.5-001` responde con precios en `normal` (≈0.25) y `reverse` (≈0.38), y sin precio en la variante con `stamp: ["set-logo"]`
- [ ] La segunda llamada al mismo endpoint no genera tráfico a `api.tcgdex.net` (verificable cortando la red)
- [ ] `app.card` sigue siendo inalcanzable desde la Data API con la llave publicable

## Qué queda explícitamente fuera de este plan

- Cualquier tabla que no sea `card` y `card_variant`
- Autenticación (el backend queda abierto en local; entra en el plan 3, junto con la captura)
- Frontend
- Búsqueda por nombre en el catálogo (`CatalogPort.search`): no la necesita ningún flujo hasta el import del Excel, así que se agrega en el plan 2 con sus propios tests
- Refresco de precios: es fase 2 del spec
