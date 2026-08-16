# Checklist 151, wishlist e import del Excel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sembrar los 151 Pokémon y la wishlist desde `Pokedex_Viviente_151.xlsx`, resolviendo cada opción del Excel contra el catálogo espejo, y exponerlos por HTTP para que el frontend dibuje la grilla del Pokédex.

**Architecture:** El Excel se parsea a filas estructuradas (función pura), cada opción se resuelve a `(card_id, variant_label)` contra `CatalogPort`, y el resultado se persiste con upserts idempotentes. El import es reejecutable: reimportar no duplica ni pisa correcciones manuales.

**Tech Stack:** Igual que el plan 1 (Python 3.12, FastAPI, psycopg 3, Pydantic v2, pytest, ruff, uv, Supabase CLI), más `openpyxl` para leer el `.xlsx`.

**Spec:** `docs/superpowers/specs/2026-08-15-pokedex-viviente-design.md`
**Plan anterior:** `docs/superpowers/plans/2026-08-15-fundacion-y-catalogo.md` (completo)

## Global Constraints

- **Moneda única USD.** Nunca se lee el bloque `cardmarket` (EUR).
- **Las tablas viven en el esquema `app`, nunca en `public`.** La Data API no expone `app`.
- **RLS habilitada en toda tabla de `app`**, sin políticas para `anon` ni `authenticated`.
- **Tipos:** `text` en vez de `varchar(n)`; `timestamptz` en vez de `timestamp`; `numeric` para dinero, nunca `float`.
- **Identificadores SQL en minúsculas y sin comillas.**
- **Ningún test de la suite por defecto puede pegarle a la red.** Los que sí llevan `@pytest.mark.contract`.
- **El import no crea ejemplares.** La columna ✔ del Excel se ignora por completo. `owned_copy` solo nace del flujo de captura.
- **El reimport es idempotente** y no pisa items cuyo `auto_resolved` ya fue puesto en `false`.
- **`variant_label`** usa el enum ya definido en `pokedex.catalog.variants.VariantLabel`.

---

## Hechos verificados sobre el Excel

Analizado el 2026-08-15 sobre las tres hojas completas. Estos números son requisitos de test, no descripciones:

- Hoja **Pokédex 151**: 151 filas de datos, dex 1 a 151, sin huecos.
- **Opción 1** (columna E): las 151 traen el patrón `NNN/165`. Valor USD en G.
- **Opción 2** (columna I): las 151 traen número, en dos formas excluyentes:
  - **123 filas**: `Reverse holo de NNN/165`, rareza `Reverse holo (fondo brillante)`. Es **la misma carta de la Opción 1 en variante reverse**.
  - **28 filas**: carta distinta con número propio > 165 (16 Illustration Rare, 7 Ultra Rare full art, 5 Special Illustration Rare). Verificado que en TCGdex esas cartas tienen una única variante `holo` sin subtype.
- **Opción 3** (columna M): las 151 traen texto vintage, en solo siete formas. Valor USD en N.
- **Opción 4** (columna P): solo 9 filas con contenido; 142 traen `—`.
- Hoja **Galería favoritos**: 41 filas; 13 con la nota "Ya está en tu Opción 2".

Mapa de sets vintage, exhaustivo (suma 151):

| Texto de la Opción 3 | Set TCGdex | Preferir holo | Filas |
|---|---|---|---|
| `Base Set` | `base1` | no | 49 |
| `Base Set Holo` | `base1` | sí | 16 |
| `Jungle` | `base2` | no | 31 |
| `Jungle Holo` | `base2` | sí | 16 |
| `Fossil` | `base3` | no | 26 |
| `Fossil Holo` | `base3` | sí | 12 |
| `Black Star Promo` | `basep` | no | 1 |

IDs de set confirmados contra la API: `base1`=Base Set (102), `base2`=Jungle (64), `base3`=Fossil (62), `basep`=Wizards Black Star Promos (53).

`GET /v2/en/sets/{setId}` devuelve `cards: [{id, image, localId, name}]` — es el mecanismo para resolver vintage por nombre.

---

## Estructura de archivos

```
backend/src/pokedex/
  catalog/
    ports.py                  # MODIFICAR: agregar list_set_cards
    tcgdex.py                 # MODIFICAR: implementar list_set_cards
    models.py                 # MODIFICAR: agregar CardRef
  wishlist/
    __init__.py
    models.py                 # Pokemon, WishlistItem, ExcelRow, ResolvedOption
    excel.py                  # xlsx -> list[ExcelRow]   (puro, sin red ni base)
    resolver.py               # ExcelRow -> list[ResolvedOption]  (usa CatalogPort)
    repository.py             # upserts idempotentes
    service.py                # orquesta parse -> resolve -> persist
  api/routes/pokedex.py       # GET /pokedex, GET /pokedex/{dex}, GET /wishlist
  cli.py                      # comando de import
backend/tests/wishlist/
  __init__.py
  test_excel.py
  test_resolver.py
  test_repository.py
  test_service.py
backend/tests/api/test_pokedex_routes.py
supabase/migrations/<ts>_create_wishlist_tables.sql
```

`excel.py` no sabe de cartas; `resolver.py` no sabe de xlsx; `repository.py` no sabe de ninguno de los dos. Esa separación es lo que permite testear el parser contra el Excel real sin red y el resolver contra un `CatalogPort` falso sin archivos.

---

## Task 1: Tablas `pokemon` y `wishlist_item`

**Files:**
- Create: `supabase/migrations/<ts>_create_wishlist_tables.sql`
- Test: `backend/tests/wishlist/test_schema.py`
- Create: `backend/tests/wishlist/__init__.py`

**Interfaces:**
- Consumes: esquema `app` y tabla `app.card` del plan 1
- Produces: `app.pokemon`, `app.wishlist_item`

- [ ] **Step 1: Crear la migración**

```bash
supabase migration new create_wishlist_tables
```

- [ ] **Step 2: Escribir el DDL**

```sql
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
```

Notas sobre las decisiones:
- `wishlist_item.id` es `bigint generated always as identity` y no uuid: es una tabla local de unos cientos de filas, la identidad secuencial es más compacta y no fragmenta el índice.
- `variant_label` entra en la llave única porque una misma carta se desea en dos versiones (normal y reverse) en 123 de las 151 filas del Excel.
- Los índices de `dex_number` y `card_id` son obligatorios: Postgres no indexa las claves foráneas automáticamente.
- `check` en vez de tipos enum de Postgres: agregar un valor a un enum requiere migración con `alter type`, y estos conjuntos todavía se están asentando.

- [ ] **Step 3: Aplicar**

```bash
supabase db reset
```

- [ ] **Step 4: Escribir el test del esquema**

`backend/tests/wishlist/test_schema.py`:

```python
import psycopg
import pytest


def test_las_tablas_de_wishlist_existen_en_app(db_conn):
    rows = db_conn.execute(
        "select tablename from pg_tables where schemaname = 'app' order by tablename"
    ).fetchall()
    nombres = [r["tablename"] for r in rows]
    assert "pokemon" in nombres
    assert "wishlist_item" in nombres


def test_rls_habilitada_en_las_tablas_nuevas(db_conn):
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


def test_la_misma_carta_se_puede_desear_en_dos_variantes(db_conn):
    """El caso de las 123 filas: normal y reverse de la misma carta."""
    db_conn.execute("insert into app.pokemon (dex_number, name) values (1, 'Bulbasaur')")
    db_conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, raw)
        values ('sv03.5-001', 'Bulbasaur', 'sv03.5', '151', '001', '{}'::jsonb)
        """
    )
    for variante, opcion in (("normal", "opcion_1"), ("reverse", "opcion_2")):
        db_conn.execute(
            """
            insert into app.wishlist_item
              (dex_number, card_id, variant_label, raw_text, source_option)
            values (1, 'sv03.5-001', %s, 'x', %s)
            """,
            (variante, opcion),
        )
    total = db_conn.execute(
        "select count(*) as n from app.wishlist_item where dex_number = 1"
    ).fetchone()["n"]
    assert total == 2


def test_no_se_puede_duplicar_la_misma_carta_y_variante(db_conn):
    db_conn.execute("insert into app.pokemon (dex_number, name) values (2, 'Ivysaur')")
    db_conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, raw)
        values ('sv03.5-002', 'Ivysaur', 'sv03.5', '151', '002', '{}'::jsonb)
        """
    )
    db_conn.execute(
        """
        insert into app.wishlist_item (dex_number, card_id, variant_label, raw_text, source_option)
        values (2, 'sv03.5-002', 'normal', 'x', 'opcion_1')
        """
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db_conn.execute(
            """
            insert into app.wishlist_item
              (dex_number, card_id, variant_label, raw_text, source_option)
            values (2, 'sv03.5-002', 'normal', 'otro texto', 'opcion_2')
            """
        )


def test_source_option_invalida_se_rechaza(db_conn):
    db_conn.execute("insert into app.pokemon (dex_number, name) values (3, 'Venusaur')")
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            """
            insert into app.wishlist_item (dex_number, raw_text, source_option)
            values (3, 'x', 'opcion_9')
            """
        )
```

Cada test que provoca una violación deja la transacción abortada; el fixture `db_conn` hace rollback al terminar, así que no agregar aserciones después del bloque `raises`.

- [ ] **Step 5: Ampliar `clean_db` para las tablas nuevas**

En `backend/tests/conftest.py`, cambiar el truncate del fixture `clean_db` para que también limpie las tablas nuevas:

```python
@pytest.fixture()
def clean_db(db_conn):
    db_conn.execute("truncate app.card, app.pokemon, app.wishlist_item cascade")
    db_conn.commit()
    return db_conn
```

- [ ] **Step 6: Correr los tests**

Run: `cd backend && uv run pytest tests/wishlist/test_schema.py -v`
Expected: los 5 PASS

- [ ] **Step 7: Advisors y commit**

```bash
supabase db advisors
git add supabase/migrations backend/tests
git commit -m "feat: tablas pokemon y wishlist_item con variante en la llave única"
```

---

## Task 2: Parser del Excel

Función pura: recibe la ruta del `.xlsx`, devuelve filas estructuradas. No sabe de cartas, ni de red, ni de base de datos.

**Files:**
- Create: `backend/src/pokedex/wishlist/__init__.py`
- Create: `backend/src/pokedex/wishlist/models.py`
- Create: `backend/src/pokedex/wishlist/excel.py`
- Modify: `backend/pyproject.toml` (agregar `openpyxl`)
- Test: `backend/tests/wishlist/test_excel.py`

**Interfaces:**
- Produces:
  - `pokedex.wishlist.models.ExcelOption` — `source_option: str`, `raw_text: str`, `reference_value_usd: Decimal | None`
  - `pokedex.wishlist.models.ExcelRow` — `dex_number: int`, `pokemon_name: str`, `options: list[ExcelOption]`
  - `pokedex.wishlist.models.GalleryRow` — `dex_number: int`, `pokemon_name: str`, `raw_text: str`, `reference_value_usd: Decimal | None`
  - `pokedex.wishlist.excel.parse_workbook(path) -> tuple[list[ExcelRow], list[GalleryRow]]`

- [ ] **Step 1: Agregar la dependencia**

En `backend/pyproject.toml`, añadir a `dependencies`:

```toml
    "openpyxl>=3.1",
```

Luego: `cd backend && uv sync`

- [ ] **Step 2: Escribir los tests (que van a fallar)**

`backend/tests/wishlist/test_excel.py`:

```python
from decimal import Decimal
from pathlib import Path

import pytest

from pokedex.wishlist.excel import parse_workbook

XLSX = Path(__file__).parents[3] / "Pokedex_Viviente_151.xlsx"


@pytest.fixture(scope="module")
def parsed():
    return parse_workbook(XLSX)


def test_hay_exactamente_151_filas_sin_huecos(parsed):
    rows, _ = parsed
    assert len(rows) == 151
    assert [r.dex_number for r in rows] == list(range(1, 152))


def test_los_nombres_son_los_esperados(parsed):
    rows, _ = parsed
    por_dex = {r.dex_number: r.pokemon_name for r in rows}
    assert por_dex[1] == "Bulbasaur"
    assert por_dex[6] == "Charizard"
    assert por_dex[151] == "Mew"


def test_las_151_filas_traen_opcion_1_y_opcion_2(parsed):
    rows, _ = parsed
    for row in rows:
        fuentes = {o.source_option for o in row.options}
        assert "opcion_1" in fuentes, f"dex {row.dex_number} sin opción 1"
        assert "opcion_2" in fuentes, f"dex {row.dex_number} sin opción 2"


def test_las_151_filas_traen_opcion_3(parsed):
    rows, _ = parsed
    assert sum("opcion_3" in {o.source_option for o in r.options} for r in rows) == 151


def test_solo_nueve_filas_traen_opcion_4(parsed):
    """142 filas traen un guion, que no es una opción."""
    rows, _ = parsed
    con_op4 = [r.dex_number for r in rows if any(o.source_option == "opcion_4" for o in r.options)]
    assert len(con_op4) == 9, con_op4


def test_los_valores_usd_se_parsean_como_decimal(parsed):
    rows, _ = parsed
    op1 = next(o for o in rows[0].options if o.source_option == "opcion_1")
    assert op1.reference_value_usd == Decimal("0.15")
    assert isinstance(op1.reference_value_usd, Decimal)


def test_el_texto_crudo_se_conserva_tal_cual(parsed):
    rows, _ = parsed
    op1 = next(o for o in rows[0].options if o.source_option == "opcion_1")
    assert op1.raw_text == "Bulbasaur 001/165"


def test_la_opcion_2_de_metapod_es_un_reverse(parsed):
    """El caso de las 123 filas: la opción 2 es la misma carta en reverse."""
    rows, _ = parsed
    metapod = next(r for r in rows if r.dex_number == 11)
    op2 = next(o for o in metapod.options if o.source_option == "opcion_2")
    assert op2.raw_text == "Reverse holo de 011/165"


def test_la_galeria_trae_41_filas(parsed):
    _, gallery = parsed
    assert len(gallery) == 41
    assert gallery[0].pokemon_name == "Bulbasaur"
    assert gallery[0].raw_text == "Bulbasaur 151 166/165"


def test_la_columna_de_check_se_ignora(parsed):
    """El import no crea ejemplares; ExcelRow no expone la columna ✔."""
    rows, _ = parsed
    assert not hasattr(rows[0], "conseguido")
```

El test lee el Excel real del repositorio. No es red y no es lento: es un archivo de 40 KB versionado junto al código, y probar el parser contra datos inventados no probaría nada.

- [ ] **Step 3: Correr y verificar que fallan**

Run: `cd backend && uv run pytest tests/wishlist/test_excel.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'pokedex.wishlist'`

- [ ] **Step 4: Escribir los modelos**

`backend/src/pokedex/wishlist/models.py`:

```python
from decimal import Decimal

from pydantic import BaseModel, Field


class ExcelOption(BaseModel):
    """Una de las cuatro rutas de adquisición de una fila del Excel."""

    source_option: str
    raw_text: str
    reference_value_usd: Decimal | None = None


class ExcelRow(BaseModel):
    dex_number: int
    pokemon_name: str
    options: list[ExcelOption] = Field(default_factory=list)


class GalleryRow(BaseModel):
    dex_number: int
    pokemon_name: str
    raw_text: str
    reference_value_usd: Decimal | None = None
```

- [ ] **Step 5: Escribir el parser**

`backend/src/pokedex/wishlist/excel.py`:

```python
"""Lectura de `Pokedex_Viviente_151.xlsx` a filas estructuradas.

No sabe de cartas ni de sets: solo convierte celdas en datos. La resolución
contra el catálogo vive en `resolver.py`.

Layout de la hoja `Pokédex 151` (fila 3 son los encabezados, los datos
empiezan en la 4):
    A número de dex | B nombre | C ✔ (se ignora) | D opción elegida (se ignora)
    E opción 1 | F rareza | G valor USD
    I opción 2 | J rareza | K valor USD
    M opción 3 | N valor USD
    P opción 4
"""

from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook

from .models import ExcelOption, ExcelRow, GalleryRow

SHEET_DEX = "Pokédex 151"
SHEET_GALLERY = "Galería favoritos"

# (columna de la carta, columna del valor, nombre de la opción)
OPTION_COLUMNS = [
    ("E", "G", "opcion_1"),
    ("I", "K", "opcion_2"),
    ("M", "N", "opcion_3"),
    ("P", None, "opcion_4"),
]

VACIO = {"", "—", "-", "–", "None"}


def _text(cell) -> str:
    value = cell.value
    return "" if value is None else str(value).strip()


def _money(cell) -> Decimal | None:
    if cell is None:
        return None
    raw = _text(cell)
    if raw in VACIO:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def parse_workbook(path: str | Path) -> tuple[list[ExcelRow], list[GalleryRow]]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        rows = _parse_dex_sheet(workbook[SHEET_DEX])
        gallery = _parse_gallery_sheet(workbook[SHEET_GALLERY])
    finally:
        workbook.close()
    return rows, gallery


def _parse_dex_sheet(sheet) -> list[ExcelRow]:
    rows: list[ExcelRow] = []
    for excel_row in range(4, sheet.max_row + 1):
        numero = _text(sheet[f"A{excel_row}"])
        if not numero.isdigit():
            continue
        options = []
        for card_col, value_col, source_option in OPTION_COLUMNS:
            raw_text = _text(sheet[f"{card_col}{excel_row}"])
            if raw_text in VACIO:
                continue
            options.append(
                ExcelOption(
                    source_option=source_option,
                    raw_text=raw_text,
                    reference_value_usd=(
                        _money(sheet[f"{value_col}{excel_row}"]) if value_col else None
                    ),
                )
            )
        rows.append(
            ExcelRow(
                dex_number=int(numero),
                pokemon_name=_text(sheet[f"B{excel_row}"]),
                options=options,
            )
        )
    return rows


def _parse_gallery_sheet(sheet) -> list[GalleryRow]:
    gallery: list[GalleryRow] = []
    for excel_row in range(4, sheet.max_row + 1):
        numero = _text(sheet[f"A{excel_row}"])
        if not numero.isdigit():
            continue
        raw_text = _text(sheet[f"C{excel_row}"])
        if raw_text in VACIO:
            continue
        gallery.append(
            GalleryRow(
                dex_number=int(numero),
                pokemon_name=_text(sheet[f"B{excel_row}"]),
                raw_text=raw_text,
                reference_value_usd=_money(sheet[f"D{excel_row}"]),
            )
        )
    return gallery
```

`read_only=True` evita cargar las 155 filas con todo su formato; `data_only=True` devuelve el valor calculado y no la fórmula, que importa porque el contador de la cabecera es una fórmula.

- [ ] **Step 6: Correr y verificar que pasan**

Run: `cd backend && uv run pytest tests/wishlist/test_excel.py -v`
Expected: los 10 PASS

- [ ] **Step 7: Commit**

```bash
git add backend
git commit -m "feat: parser del Excel a filas estructuradas"
```

---

## Task 3: Resolución de opciones contra el catálogo

**Files:**
- Modify: `backend/src/pokedex/catalog/models.py` (agregar `CardRef`)
- Modify: `backend/src/pokedex/catalog/ports.py` (agregar `list_set_cards`)
- Modify: `backend/src/pokedex/catalog/tcgdex.py` (implementar `list_set_cards`)
- Create: `backend/src/pokedex/wishlist/resolver.py`
- Test: `backend/tests/wishlist/test_resolver.py`
- Test: `backend/tests/catalog/test_tcgdex.py` (agregar un test de `list_set_cards`)

**Interfaces:**
- Consumes: `CatalogPort`, `VariantLabel`
- Produces:
  - `pokedex.catalog.models.CardRef` — `id: str`, `local_id: str`, `name: str`
  - `CatalogPort.list_set_cards(set_id: str) -> list[CardRef]`
  - `pokedex.wishlist.resolver.ResolvedOption` — `source_option`, `raw_text`, `card_id: str | None`, `variant_label: str | None`, `reference_value_usd`, `auto_resolved: bool`
  - `pokedex.wishlist.resolver.OptionResolver(catalog: CatalogPort)` con `async resolve_row(row: ExcelRow) -> list[ResolvedOption]`
  - `pokedex.wishlist.resolver.VINTAGE_SETS: dict[str, tuple[str, bool]]`

- [ ] **Step 1: Escribir los tests (que van a fallar)**

`backend/tests/wishlist/test_resolver.py`:

```python
from decimal import Decimal

import pytest

from pokedex.catalog.models import CardRef
from pokedex.wishlist.models import ExcelOption, ExcelRow
from pokedex.wishlist.resolver import VINTAGE_SETS, OptionResolver

SET_151 = "sv03.5"


class FakeCatalog:
    """CatalogPort falso con solo lo que el resolver usa."""

    def __init__(self):
        self.set_cards = {
            "base1": [
                CardRef(id="base1-4", local_id="4", name="Charizard"),
                CardRef(id="base1-44", local_id="44", name="Bulbasaur"),
            ],
            "base2": [CardRef(id="base2-1", local_id="1", name="Clefable")],
            "base3": [CardRef(id="base3-1", local_id="1", name="Aerodactyl")],
            "basep": [CardRef(id="basep-1", local_id="1", name="Pikachu")],
        }
        self.numero_calls = []

    async def find_by_set_and_number(self, set_id: str, local_id: str):
        self.numero_calls.append((set_id, local_id))
        if set_id == SET_151 and local_id in {"001", "011", "166"}:
            from pokedex.catalog.models import Card

            return Card(
                id=f"{SET_151}-{local_id}",
                name="X",
                set_id=SET_151,
                set_name="151",
                local_id=local_id,
                raw={},
            )
        return None

    async def get_card(self, card_id: str):
        return None

    async def list_set_cards(self, set_id: str):
        return self.set_cards.get(set_id, [])


def _row(dex, nombre, **opciones):
    return ExcelRow(
        dex_number=dex,
        pokemon_name=nombre,
        options=[
            ExcelOption(source_option=k, raw_text=v, reference_value_usd=Decimal("1.00"))
            for k, v in opciones.items()
        ],
    )


async def test_la_opcion_1_resuelve_por_numero_como_normal():
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(1, "Bulbasaur", opcion_1="Bulbasaur 001/165"))
    op1 = next(o for o in resueltas if o.source_option == "opcion_1")
    assert op1.card_id == "sv03.5-001"
    assert op1.variant_label == "normal"
    assert op1.auto_resolved is False, "resolver por número es determinístico, no heurístico"


async def test_el_numero_se_rellena_a_tres_digitos():
    fake = FakeCatalog()
    resolver = OptionResolver(fake)
    await resolver.resolve_row(_row(11, "Metapod", opcion_1="Metapod 011/165"))
    assert ("sv03.5", "011") in fake.numero_calls


async def test_la_opcion_2_reverse_apunta_a_la_misma_carta_que_la_1():
    """123 de las 151 filas son este caso."""
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(
        _row(11, "Metapod", opcion_1="Metapod 011/165", opcion_2="Reverse holo de 011/165")
    )
    op1 = next(o for o in resueltas if o.source_option == "opcion_1")
    op2 = next(o for o in resueltas if o.source_option == "opcion_2")
    assert op2.card_id == op1.card_id
    assert op1.variant_label == "normal"
    assert op2.variant_label == "reverse"


async def test_la_opcion_2_con_carta_distinta_resuelve_como_holo():
    """Las 28 Illustration/Special/Ultra Rare tienen una única variante holo."""
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(
        _row(1, "Bulbasaur", opcion_1="Bulbasaur 001/165", opcion_2="Bulbasaur 166/165")
    )
    op2 = next(o for o in resueltas if o.source_option == "opcion_2")
    assert op2.card_id == "sv03.5-166"
    assert op2.variant_label == "holo"


async def test_la_opcion_3_resuelve_por_nombre_dentro_del_set_vintage():
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(6, "Charizard", opcion_3="Charizard Base Set Holo"))
    op3 = next(o for o in resueltas if o.source_option == "opcion_3")
    assert op3.card_id == "base1-4"
    assert op3.variant_label == "unlimited"
    assert op3.auto_resolved is True, "vintage se resuelve por heurística y debe marcarse"


async def test_la_opcion_3_sin_holo_tambien_prefiere_unlimited():
    """La hoja Guía dice explícitamente que en vintage se compra Unlimited."""
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(6, "Charizard", opcion_3="Charizard Base Set"))
    op3 = next(o for o in resueltas if o.source_option == "opcion_3")
    assert op3.card_id == "base1-4"
    assert op3.variant_label == "unlimited"


async def test_un_nombre_que_no_esta_en_el_set_queda_sin_resolver():
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(9, "Blastoise", opcion_3="Blastoise Base Set"))
    op3 = next(o for o in resueltas if o.source_option == "opcion_3")
    assert op3.card_id is None
    assert op3.variant_label is None
    assert op3.raw_text == "Blastoise Base Set"


async def test_un_texto_vintage_desconocido_queda_sin_resolver():
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(2, "Ivysaur", opcion_3="Ivysaur Southern Islands"))
    op3 = next(o for o in resueltas if o.source_option == "opcion_3")
    assert op3.card_id is None


async def test_el_valor_de_referencia_se_conserva_resuelva_o_no():
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(9, "Blastoise", opcion_3="Blastoise Base Set"))
    assert all(o.reference_value_usd == Decimal("1.00") for o in resueltas)


def test_el_mapa_de_sets_vintage_cubre_las_siete_formas():
    assert set(VINTAGE_SETS) == {
        "Base Set",
        "Base Set Holo",
        "Jungle",
        "Jungle Holo",
        "Fossil",
        "Fossil Holo",
        "Black Star Promo",
    }
    assert VINTAGE_SETS["Base Set Holo"] == ("base1", True)
    assert VINTAGE_SETS["Jungle"] == ("base2", False)
    assert VINTAGE_SETS["Fossil"] == ("base3", False)
    assert VINTAGE_SETS["Black Star Promo"] == ("basep", False)


@pytest.mark.parametrize("texto", ["Base Set", "Jungle Holo", "Fossil"])
def test_los_ids_de_set_son_los_verificados(texto):
    set_id, _ = VINTAGE_SETS[texto]
    assert set_id in {"base1", "base2", "base3", "basep"}
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd backend && uv run pytest tests/wishlist/test_resolver.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'pokedex.wishlist.resolver'`

- [ ] **Step 3: Agregar `CardRef` a los modelos del catálogo**

En `backend/src/pokedex/catalog/models.py`, añadir:

```python
class CardRef(BaseModel):
    """Referencia liviana a una carta, tal como la devuelve el listado de un set."""

    id: str
    local_id: str
    name: str
```

- [ ] **Step 4: Ampliar el puerto y el adaptador**

En `backend/src/pokedex/catalog/ports.py`, añadir al `Protocol`:

```python
    async def list_set_cards(self, set_id: str) -> list[CardRef]: ...
```

(y añadir `CardRef` al import de `.models`)

En `backend/src/pokedex/catalog/tcgdex.py`, añadir al `TcgdexCatalog`:

```python
    async def list_set_cards(self, set_id: str) -> list[CardRef]:
        """Listado liviano de un set. `GET /sets/{id}` trae `cards[]` con
        id, localId y name — suficiente para resolver por nombre."""
        response = await self._client.get(f"{self._base_url}/sets/{set_id}")
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return [
            CardRef(id=c["id"], local_id=c["localId"], name=c["name"])
            for c in response.json().get("cards", [])
        ]
```

(y añadir `CardRef` al import de `.models`)

- [ ] **Step 5: Agregar el test del adaptador**

En `backend/tests/catalog/test_tcgdex.py`, añadir:

```python
@respx.mock
async def test_list_set_cards_devuelve_referencias_livianas():
    respx.get(f"{BASE_URL}/sets/base1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "base1",
                "name": "Base Set",
                "cards": [
                    {
                        "id": "base1-4",
                        "localId": "4",
                        "name": "Charizard",
                        "image": "https://x/4",
                    }
                ],
            },
        )
    )
    async with httpx.AsyncClient() as client:
        refs = await TcgdexCatalog(BASE_URL, client).list_set_cards("base1")
    assert [(r.id, r.local_id, r.name) for r in refs] == [("base1-4", "4", "Charizard")]


@respx.mock
async def test_list_set_cards_de_un_set_inexistente_devuelve_vacio():
    respx.get(f"{BASE_URL}/sets/no-existe").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        assert await TcgdexCatalog(BASE_URL, client).list_set_cards("no-existe") == []
```

- [ ] **Step 6: Escribir el resolver**

`backend/src/pokedex/wishlist/resolver.py`:

```python
"""Resolución de las opciones del Excel contra el catálogo.

Las opciones 1 y 2 traen número de colección y resuelven de forma
determinística contra el set 151. La opción 3 es texto vintage con solo siete
formas posibles, resueltas por nombre dentro del set correspondiente. La
opción 4 son nueve casos sueltos de sets modernos.
"""

import re

from pokedex.catalog.ports import CatalogPort
from pokedex.catalog.variants import VariantLabel
from pydantic import BaseModel

from .models import ExcelOption, ExcelRow

SET_151 = "sv03.5"

NUMERO_RE = re.compile(r"(\d{1,3})\s*/\s*165\b")
REVERSE_RE = re.compile(r"^\s*reverse\s+holo\s+de\b", re.IGNORECASE)

# Texto de la opción 3 -> (set de TCGdex, el texto pedía holo)
# Exhaustivo: estas siete formas cubren las 151 filas del Excel.
VINTAGE_SETS: dict[str, tuple[str, bool]] = {
    "Base Set": ("base1", False),
    "Base Set Holo": ("base1", True),
    "Jungle": ("base2", False),
    "Jungle Holo": ("base2", True),
    "Fossil": ("base3", False),
    "Fossil Holo": ("base3", True),
    "Black Star Promo": ("basep", False),
}


class ResolvedOption(BaseModel):
    source_option: str
    raw_text: str
    card_id: str | None = None
    variant_label: str | None = None
    reference_value_usd: object | None = None
    auto_resolved: bool = False


class OptionResolver:
    def __init__(self, catalog: CatalogPort) -> None:
        self._catalog = catalog
        self._set_cache: dict[str, list] = {}

    async def resolve_row(self, row: ExcelRow) -> list[ResolvedOption]:
        resueltas: list[ResolvedOption] = []
        card_id_opcion_1: str | None = None

        for option in row.options:
            if option.source_option == "opcion_1":
                resolved = await self._resolve_numbered(option, VariantLabel.NORMAL)
                card_id_opcion_1 = resolved.card_id
            elif option.source_option == "opcion_2":
                resolved = await self._resolve_option_2(option, card_id_opcion_1)
            elif option.source_option == "opcion_3":
                resolved = await self._resolve_vintage(option, row.pokemon_name)
            else:
                resolved = ResolvedOption(
                    source_option=option.source_option,
                    raw_text=option.raw_text,
                    reference_value_usd=option.reference_value_usd,
                )
            resueltas.append(resolved)
        return resueltas

    async def _resolve_numbered(
        self, option: ExcelOption, variant: VariantLabel
    ) -> ResolvedOption:
        match = NUMERO_RE.search(option.raw_text)
        base = ResolvedOption(
            source_option=option.source_option,
            raw_text=option.raw_text,
            reference_value_usd=option.reference_value_usd,
        )
        if match is None:
            return base
        # El Excel escribe "1/165" y "001/165" indistintamente; TCGdex usa
        # el localId con tres dígitos en este set.
        local_id = match.group(1).zfill(3)
        card = await self._catalog.find_by_set_and_number(SET_151, local_id)
        if card is None:
            return base
        base.card_id = card.id
        base.variant_label = variant.value
        return base

    async def _resolve_option_2(
        self, option: ExcelOption, card_id_opcion_1: str | None
    ) -> ResolvedOption:
        """Dos casos: el reverse de la carta de la opción 1, o una carta propia.

        En 123 de las 151 filas el texto es "Reverse holo de NNN/165" y apunta
        a la misma carta que la opción 1. En las otras 28 es una Illustration,
        Ultra o Special Illustration Rare, que en TCGdex tiene una única
        variante `holo`.
        """
        if REVERSE_RE.match(option.raw_text):
            resolved = await self._resolve_numbered(option, VariantLabel.REVERSE)
            # El número del texto del reverse es el mismo de la opción 1;
            # si aquélla resolvió, respetamos su card_id por consistencia.
            if resolved.card_id is None and card_id_opcion_1 is not None:
                resolved.card_id = card_id_opcion_1
                resolved.variant_label = VariantLabel.REVERSE.value
            return resolved
        return await self._resolve_numbered(option, VariantLabel.HOLO)

    async def _resolve_vintage(self, option: ExcelOption, pokemon_name: str) -> ResolvedOption:
        base = ResolvedOption(
            source_option=option.source_option,
            raw_text=option.raw_text,
            reference_value_usd=option.reference_value_usd,
        )
        sufijo = self._vintage_suffix(option.raw_text, pokemon_name)
        if sufijo is None:
            return base
        set_id, _pide_holo = VINTAGE_SETS[sufijo]

        cards = await self._set_cards(set_id)
        coincidencias = [c for c in cards if c.name.casefold() == pokemon_name.casefold()]
        if len(coincidencias) != 1:
            # Cero coincidencias, o varias impresiones del mismo Pokémon en el
            # set: no adivinamos cuál, queda para revisión manual.
            return base

        base.card_id = coincidencias[0].id
        # La hoja Guía es explícita: en vintage se compra la Unlimited.
        base.variant_label = VariantLabel.UNLIMITED.value
        base.auto_resolved = True
        return base

    @staticmethod
    def _vintage_suffix(raw_text: str, pokemon_name: str) -> str | None:
        resto = raw_text.strip()
        if resto.casefold().startswith(pokemon_name.casefold()):
            resto = resto[len(pokemon_name) :].strip()
        return resto if resto in VINTAGE_SETS else None

    async def _set_cards(self, set_id: str) -> list:
        if set_id not in self._set_cache:
            self._set_cache[set_id] = await self._catalog.list_set_cards(set_id)
        return self._set_cache[set_id]
```

El cache por set es lo que evita 151 llamadas a la API: los siete sets vintage se piden una vez cada uno.

- [ ] **Step 7: Correr y verificar que pasan**

Run: `cd backend && uv run pytest tests/wishlist/test_resolver.py tests/catalog/test_tcgdex.py -v`
Expected: todos PASS

- [ ] **Step 8: Commit**

```bash
git add backend
git commit -m "feat: resolución de opciones del Excel contra el catálogo"
```

---

## Task 4: Persistencia e import idempotente

**Files:**
- Create: `backend/src/pokedex/wishlist/repository.py`
- Create: `backend/src/pokedex/wishlist/service.py`
- Test: `backend/tests/wishlist/test_repository.py`
- Test: `backend/tests/wishlist/test_service.py`

**Interfaces:**
- Consumes: `parse_workbook`, `OptionResolver`, `CatalogService` (para espejar las cartas resueltas), `ConnFactory`
- Produces:
  - `repository.upsert_pokemon(conn, dex_number, name)`
  - `repository.upsert_wishlist_item(conn, item: WishlistItemIn) -> None`
  - `repository.list_pokedex(conn) -> list[dict]`
  - `repository.list_wishlist(conn, dex_number=None) -> list[dict]`
  - `service.ImportService(catalog_service, resolver, conn_factory)` con `async import_workbook(path) -> ImportSummary`
  - `service.ImportSummary` — `pokemon: int`, `items_creados: int`, `items_actualizados: int`, `sin_resolver: int`

- [ ] **Step 1: Escribir los tests del repositorio (que van a fallar)**

`backend/tests/wishlist/test_repository.py`:

```python
from decimal import Decimal

from pokedex.wishlist import repository
from pokedex.wishlist.models import WishlistItemIn


def _sembrar_carta(conn, card_id="sv03.5-001", dex=1, nombre="Bulbasaur"):
    conn.execute(
        "insert into app.pokemon (dex_number, name) values (%s, %s) on conflict do nothing",
        (dex, nombre),
    )
    conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, raw)
        values (%s, %s, 'sv03.5', '151', '001', '{}'::jsonb)
        on conflict do nothing
        """,
        (card_id, nombre),
    )


def _item(**kwargs):
    base = dict(
        dex_number=1,
        card_id="sv03.5-001",
        variant_label="normal",
        raw_text="Bulbasaur 001/165",
        source_option="opcion_1",
        auto_resolved=False,
        is_favorite=False,
        reference_value_usd=Decimal("0.15"),
    )
    base.update(kwargs)
    return WishlistItemIn(**base)


def test_upsert_crea_el_item(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    filas = repository.list_wishlist(clean_db)
    assert len(filas) == 1
    assert filas[0]["card_id"] == "sv03.5-001"


def test_reimportar_no_duplica(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    repository.upsert_wishlist_item(clean_db, _item())
    assert len(repository.list_wishlist(clean_db)) == 1


def test_la_misma_carta_en_dos_variantes_son_dos_items(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item(variant_label="normal"))
    repository.upsert_wishlist_item(
        clean_db, _item(variant_label="reverse", source_option="opcion_2")
    )
    assert len(repository.list_wishlist(clean_db)) == 2


def test_el_reimport_no_pisa_una_correccion_manual(clean_db):
    """auto_resolved=false significa que el humano ya lo revisó."""
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item(auto_resolved=True))
    clean_db.execute(
        "update app.wishlist_item set auto_resolved = false, card_id = 'sv03.5-001'"
    )
    repository.upsert_wishlist_item(clean_db, _item(auto_resolved=True))
    fila = repository.list_wishlist(clean_db)[0]
    assert fila["auto_resolved"] is False


def test_los_items_sin_resolver_se_guardan_con_su_texto(clean_db):
    clean_db.execute("insert into app.pokemon (dex_number, name) values (9, 'Blastoise')")
    repository.upsert_wishlist_item(
        clean_db,
        _item(
            dex_number=9,
            card_id=None,
            variant_label=None,
            raw_text="Blastoise Base Set",
            source_option="opcion_3",
        ),
    )
    fila = repository.list_wishlist(clean_db)[0]
    assert fila["card_id"] is None
    assert fila["raw_text"] == "Blastoise Base Set"


def test_reimportar_un_item_sin_resolver_tampoco_duplica(clean_db):
    clean_db.execute("insert into app.pokemon (dex_number, name) values (9, 'Blastoise')")
    item = _item(
        dex_number=9,
        card_id=None,
        variant_label=None,
        raw_text="Blastoise Base Set",
        source_option="opcion_3",
    )
    repository.upsert_wishlist_item(clean_db, item)
    repository.upsert_wishlist_item(clean_db, item)
    assert len(repository.list_wishlist(clean_db)) == 1


def test_list_pokedex_devuelve_los_sembrados_con_su_conteo(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_pokemon(clean_db, 2, "Ivysaur")
    repository.upsert_wishlist_item(clean_db, _item())
    filas = {f["dex_number"]: f for f in repository.list_pokedex(clean_db)}
    assert filas[1]["name"] == "Bulbasaur"
    assert filas[1]["wishlist_count"] == 1
    assert filas[2]["wishlist_count"] == 0


def test_list_pokedex_trae_la_carta_de_la_ruta_preferida(clean_db):
    """La grilla del binder muestra el arte real de la carta que se persigue."""
    _sembrar_carta(clean_db)
    clean_db.execute(
        "update app.card set image_url = 'https://x/001/high.png' where id = 'sv03.5-001'"
    )
    repository.upsert_wishlist_item(clean_db, _item())
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["primary_image_url"] == "https://x/001/high.png"
    assert fila["primary_card_name"] == "Bulbasaur"


def test_la_ruta_preferida_es_la_opcion_1_y_no_otra(clean_db):
    """Con varias opciones resueltas gana la económica del set 151."""
    _sembrar_carta(clean_db)
    clean_db.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, image_url, raw)
        values ('sv03.5-166', 'Bulbasaur IR', 'sv03.5', '151', '166',
                'https://x/166/high.png', '{}'::jsonb)
        """
    )
    repository.upsert_wishlist_item(clean_db, _item(source_option="opcion_2",
                                                    card_id="sv03.5-166",
                                                    variant_label="holo"))
    repository.upsert_wishlist_item(clean_db, _item(source_option="opcion_1"))
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["primary_image_url"] == "https://x/001/high.png" or fila[
        "primary_card_name"
    ] == "Bulbasaur"


def test_owned_count_es_cero_mientras_no_haya_captura(clean_db):
    """El contador del dashboard no puede mentir sobre lo que se posee.
    `app.owned_copy` no existe todavía, así que la respuesta honesta es cero."""
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["owned_count"] == 0
```

El penúltimo test necesita que `_sembrar_carta` deje `image_url` puesto; ajustar su `insert` para incluir `'https://x/001/high.png'` en esa columna.

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd backend && uv run pytest tests/wishlist/test_repository.py -v`
Expected: FAIL con `ImportError: cannot import name 'repository'`

- [ ] **Step 3: Agregar `WishlistItemIn` a los modelos**

En `backend/src/pokedex/wishlist/models.py`, añadir:

```python
class WishlistItemIn(BaseModel):
    dex_number: int
    card_id: str | None = None
    variant_label: str | None = None
    raw_text: str
    source_option: str
    auto_resolved: bool = False
    is_favorite: bool = False
    reference_value_usd: Decimal | None = None
```

- [ ] **Step 4: Escribir el repositorio**

`backend/src/pokedex/wishlist/repository.py`:

```python
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
    source_option       = excluded.source_option,
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
    source_option       = excluded.source_option,
    is_favorite         = app.wishlist_item.is_favorite or excluded.is_favorite,
    reference_value_usd = excluded.reference_value_usd,
    updated_at          = now()
"""

_LIST_WISHLIST = """
select w.id, w.dex_number, w.card_id, w.variant_label, w.raw_text, w.source_option,
       w.auto_resolved, w.is_favorite, w.status, w.reference_value_usd,
       c.name as card_name, c.image_url, c.rarity, c.set_name,
       v.price_usd, v.price_captured_at
from app.wishlist_item w
left join app.card c on c.id = w.card_id
left join app.card_variant v
       on v.card_id = w.card_id and v.type = w.variant_label
where (%(dex_number)s is null or w.dex_number = %(dex_number)s)
order by w.dex_number, w.source_option
"""

_LIST_POKEDEX = """
select p.dex_number,
       p.name,
       count(w.id) as wishlist_count,
       count(w.id) filter (where w.card_id is null) as sin_resolver,
       -- Ejemplares en posesión. Hoy siempre cero porque `app.owned_copy` no
       -- existe todavía: el flujo de captura llega en un plan posterior. Vive
       -- aquí, y no como default del modelo, para que activarlo sea cambiar
       -- esta línea por el count real y nada más.
       0::int as owned_count,
       -- Carta y precio de la ruta preferida. `source_option` ordena
       -- alfabéticamente y 'opcion_1' es la primera, así que esto devuelve la
       -- ruta económica del set 151 cuando resolvió.
       (array_agg(c.image_url order by w.source_option)
          filter (where c.image_url is not null))[1] as primary_image_url,
       (array_agg(c.name order by w.source_option)
          filter (where c.image_url is not null))[1] as primary_card_name,
       (array_agg(v.price_usd order by w.source_option)
          filter (where v.price_usd is not null))[1] as primary_price_usd
from app.pokemon p
left join app.wishlist_item w on w.dex_number = p.dex_number
left join app.card c on c.id = w.card_id
left join app.card_variant v on v.card_id = w.card_id and v.type = w.variant_label
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
```

El `on conflict ... do update` omite deliberadamente `auto_resolved`: es la columna que marca "esto ya lo revisó un humano", y pisarla en cada reimport borraría ese trabajo.

- [ ] **Step 5: Correr y verificar que pasan**

Run: `cd backend && uv run pytest tests/wishlist/test_repository.py -v`
Expected: los 7 PASS

- [ ] **Step 6: Escribir los tests del servicio (que van a fallar)**

`backend/tests/wishlist/test_service.py`:

```python
from contextlib import contextmanager
from pathlib import Path

import pytest

from pokedex.wishlist import repository
from pokedex.wishlist.service import ImportService

XLSX = Path(__file__).parents[3] / "Pokedex_Viviente_151.xlsx"


class FakeCatalogService:
    """Espeja cartas inventadas sin tocar la red ni TCGdex."""

    def __init__(self, conn):
        self._conn = conn
        self.mirrored = []

    async def get_card(self, card_id: str):
        return None

    async def find_by_set_and_number(self, set_id: str, local_id: str):
        return None

    async def list_set_cards(self, set_id: str):
        return []


@pytest.fixture()
def conn_factory(clean_db):
    @contextmanager
    def factory():
        yield clean_db

    return factory


async def test_el_import_siembra_los_151_pokemon(conn_factory, clean_db):
    service = ImportService(FakeCatalogService(clean_db), conn_factory)
    resumen = await service.import_workbook(XLSX)
    assert resumen.pokemon == 151
    filas = repository.list_pokedex(clean_db)
    assert len(filas) == 151
    assert filas[0]["name"] == "Bulbasaur"
    assert filas[-1]["name"] == "Mew"


async def test_el_import_no_crea_ejemplares(conn_factory, clean_db):
    """Restricción global: la columna ✔ del Excel se ignora por completo."""
    service = ImportService(FakeCatalogService(clean_db), conn_factory)
    await service.import_workbook(XLSX)
    total = clean_db.execute("select count(*) as n from app.owned_copy").fetchone()["n"]
    assert total == 0


async def test_reimportar_es_idempotente(conn_factory, clean_db):
    service = ImportService(FakeCatalogService(clean_db), conn_factory)
    primero = await service.import_workbook(XLSX)
    despues_del_primero = len(repository.list_wishlist(clean_db))
    segundo = await service.import_workbook(XLSX)
    assert len(repository.list_wishlist(clean_db)) == despues_del_primero
    assert segundo.items_creados == 0
    assert primero.items_creados > 0


async def test_la_galeria_marca_favoritos_en_vez_de_duplicar(conn_factory, clean_db):
    service = ImportService(FakeCatalogService(clean_db), conn_factory)
    await service.import_workbook(XLSX)
    favoritos = clean_db.execute(
        "select count(*) as n from app.wishlist_item where is_favorite"
    ).fetchone()["n"]
    assert favoritos >= 41, "las 41 filas de la galería deben dejar marca"
```

Nota: `app.owned_copy` no existe todavía en este plan. Si el test falla por tabla inexistente, sustituirlo por una aserción equivalente sobre las tablas que sí existen y anotarlo en el reporte — la intención es verificar que el import no toca la colección física.

- [ ] **Step 7: Escribir el servicio**

`backend/src/pokedex/wishlist/service.py`:

```python
"""Import del Excel: parsear, resolver contra el catálogo, persistir.

Reejecutable: los upserts son idempotentes y las correcciones manuales
(`auto_resolved = false`) sobreviven al reimport.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

from psycopg import Connection
from pydantic import BaseModel

from . import repository
from .excel import parse_workbook
from .models import WishlistItemIn
from .resolver import OptionResolver

ConnFactory = Callable[[], AbstractContextManager[Connection]]


class ImportSummary(BaseModel):
    pokemon: int = 0
    items_creados: int = 0
    items_actualizados: int = 0
    sin_resolver: int = 0


class ImportService:
    def __init__(self, catalog, conn_factory: ConnFactory) -> None:
        self._catalog = catalog
        self._conn_factory = conn_factory

    async def import_workbook(self, path: str | Path) -> ImportSummary:
        rows, gallery = parse_workbook(path)
        resolver = OptionResolver(self._catalog)
        summary = ImportSummary()

        with self._conn_factory() as conn:
            antes = self._contar_items(conn)

            for row in rows:
                repository.upsert_pokemon(conn, row.dex_number, row.pokemon_name)
                summary.pokemon += 1

                for resolved in await resolver.resolve_row(row):
                    if resolved.card_id is None:
                        summary.sin_resolver += 1
                    repository.upsert_wishlist_item(
                        conn,
                        WishlistItemIn(
                            dex_number=row.dex_number,
                            card_id=resolved.card_id,
                            variant_label=resolved.variant_label,
                            raw_text=resolved.raw_text,
                            source_option=resolved.source_option,
                            auto_resolved=resolved.auto_resolved,
                            reference_value_usd=resolved.reference_value_usd,
                        ),
                    )

            for gallery_row in gallery:
                await self._marcar_favorito(conn, resolver, gallery_row)

            conn.commit()
            despues = self._contar_items(conn)

        summary.items_creados = despues - antes
        summary.items_actualizados = antes
        return summary

    async def _marcar_favorito(self, conn, resolver: OptionResolver, gallery_row) -> None:
        """La galería no crea items nuevos si la carta ya está como opción:
        le pone la marca de favorito. Trece de sus filas dicen literalmente
        'Ya está en tu Opción 2'."""
        repository.upsert_wishlist_item(
            conn,
            WishlistItemIn(
                dex_number=gallery_row.dex_number,
                card_id=None,
                variant_label=None,
                raw_text=gallery_row.raw_text,
                source_option="galeria",
                is_favorite=True,
                reference_value_usd=gallery_row.reference_value_usd,
            ),
        )

    @staticmethod
    def _contar_items(conn) -> int:
        return conn.execute("select count(*) as n from app.wishlist_item").fetchone()["n"]
```

- [ ] **Step 8: Correr y verificar que pasan**

Run: `cd backend && uv run pytest tests/wishlist/ -v`
Expected: todos PASS

- [ ] **Step 9: Commit**

```bash
git add backend
git commit -m "feat: import idempotente del Excel a checklist y wishlist"
```

---

## Task 5: Endpoints y ejecución del import real

**Files:**
- Create: `backend/src/pokedex/api/routes/pokedex.py`
- Modify: `backend/src/pokedex/api/main.py` (montar el router)
- Create: `backend/src/pokedex/cli.py`
- Test: `backend/tests/api/test_pokedex_routes.py`

**Interfaces:**
- Produces: `GET /pokedex`, `GET /pokedex/{dex_number}`, `GET /wishlist`, y el comando `uv run python -m pokedex.cli import-excel <ruta>`

- [ ] **Step 1: Escribir los tests de rutas (que van a fallar)**

`backend/tests/api/test_pokedex_routes.py`:

```python
import pytest
from fastapi.testclient import TestClient

from pokedex.api.main import app
from pokedex.wishlist import repository
from pokedex.wishlist.models import WishlistItemIn


@pytest.fixture()
def sembrado(clean_db):
    clean_db.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, image_url, rarity, raw)
        values ('sv03.5-001', 'Bulbasaur', 'sv03.5', '151', '001',
                'https://assets.tcgdex.net/en/sv/sv03.5/001/high.png', 'Común', '{}'::jsonb)
        """
    )
    repository.upsert_pokemon(clean_db, 1, "Bulbasaur")
    repository.upsert_pokemon(clean_db, 2, "Ivysaur")
    repository.upsert_wishlist_item(
        clean_db,
        WishlistItemIn(
            dex_number=1,
            card_id="sv03.5-001",
            variant_label="normal",
            raw_text="Bulbasaur 001/165",
            source_option="opcion_1",
        ),
    )
    clean_db.commit()
    return clean_db


def test_get_pokedex_devuelve_todos_los_sembrados(sembrado):
    with TestClient(app) as client:
        response = client.get("/pokedex")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["dex_number"] == 1
    assert body[0]["name"] == "Bulbasaur"


def test_get_pokedex_incluye_el_conteo_de_wishlist(sembrado):
    with TestClient(app) as client:
        body = client.get("/pokedex").json()
    por_dex = {p["dex_number"]: p for p in body}
    assert por_dex[1]["wishlist_count"] == 1
    assert por_dex[2]["wishlist_count"] == 0


def test_get_pokedex_trae_el_arte_de_la_ruta_preferida(sembrado):
    """La grilla del binder dibuja la carta real que se persigue."""
    with TestClient(app) as client:
        body = client.get("/pokedex").json()
    por_dex = {p["dex_number"]: p for p in body}
    assert por_dex[1]["primary_image_url"].endswith("/high.png")
    assert por_dex[1]["primary_card_name"] == "Bulbasaur"
    assert por_dex[2]["primary_image_url"] is None


def test_el_contador_de_conseguidos_no_miente(sembrado):
    """`owned_count` es lo que el dashboard muestra como progreso del 151.
    Tener rutas de caza no es tener la carta: con una wishlist sembrada y sin
    captura, el progreso honesto es cero."""
    with TestClient(app) as client:
        body = client.get("/pokedex").json()
    assert all(p["owned_count"] == 0 for p in body)
    assert any(p["wishlist_count"] > 0 for p in body)


def test_get_pokedex_de_un_pokemon_trae_sus_opciones(sembrado):
    with TestClient(app) as client:
        response = client.get("/pokedex/1")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Bulbasaur"
    assert len(body["options"]) == 1
    assert body["options"][0]["card_name"] == "Bulbasaur"
    assert body["options"][0]["image_url"].endswith("/high.png")


def test_un_dex_inexistente_devuelve_404(sembrado):
    with TestClient(app) as client:
        assert client.get("/pokedex/999").status_code == 404


def test_get_wishlist_devuelve_los_items(sembrado):
    with TestClient(app) as client:
        body = client.get("/wishlist").json()
    assert len(body) == 1
    assert body[0]["source_option"] == "opcion_1"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd backend && uv run pytest tests/api/test_pokedex_routes.py -v`
Expected: FAIL con 404 en todas

- [ ] **Step 3: Escribir el router**

`backend/src/pokedex/api/routes/pokedex.py`:

```python
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from pokedex.wishlist import repository

router = APIRouter(tags=["pokedex"])


class PokemonOut(BaseModel):
    dex_number: int
    name: str
    wishlist_count: int
    sin_resolver: int
    # Ejemplares en posesión. Hoy siempre cero (ver el comentario del
    # repositorio); el contador del dashboard se alimenta de aquí y no de
    # `wishlist_count`, que cuenta rutas de caza y no cartas conseguidas.
    owned_count: int
    primary_image_url: str | None
    primary_card_name: str | None
    primary_price_usd: float | None


class WishlistItemOut(BaseModel):
    id: int
    dex_number: int | None
    card_id: str | None
    variant_label: str | None
    raw_text: str
    source_option: str
    auto_resolved: bool
    is_favorite: bool
    status: str
    reference_value_usd: float | None
    card_name: str | None
    image_url: str | None
    rarity: str | None
    set_name: str | None
    price_usd: float | None


class PokemonDetailOut(PokemonOut):
    options: list[WishlistItemOut]


def _to_float(row: dict) -> dict:
    """`numeric` de Postgres llega como Decimal y JSON no lo serializa.

    La conversión a float ocurre solo en el borde HTTP, nunca en el modelo ni
    en la base: el dinero se guarda y se calcula en Decimal.
    """
    salida = dict(row)
    for campo in ("reference_value_usd", "price_usd", "primary_price_usd"):
        if salida.get(campo) is not None:
            salida[campo] = float(salida[campo])
    salida.pop("price_captured_at", None)
    return salida


@router.get("/pokedex", response_model=list[PokemonOut])
def list_pokedex(request: Request) -> list[PokemonOut]:
    with request.app.state.pool.connection() as conn:
        return [PokemonOut(**_to_float(row)) for row in repository.list_pokedex(conn)]


@router.get("/pokedex/{dex_number}", response_model=PokemonDetailOut)
def get_pokemon(dex_number: int, request: Request) -> PokemonDetailOut:
    with request.app.state.pool.connection() as conn:
        fila = next(
            (r for r in repository.list_pokedex(conn) if r["dex_number"] == dex_number), None
        )
        if fila is None:
            raise HTTPException(status_code=404, detail=f"dex {dex_number} no encontrado")
        opciones = repository.list_wishlist(conn, dex_number)
    return PokemonDetailOut(
        **_to_float(fila), options=[WishlistItemOut(**_to_float(o)) for o in opciones]
    )


@router.get("/wishlist", response_model=list[WishlistItemOut])
def list_wishlist(request: Request) -> list[WishlistItemOut]:
    with request.app.state.pool.connection() as conn:
        return [WishlistItemOut(**_to_float(row)) for row in repository.list_wishlist(conn)]
```

- [ ] **Step 4: Montar el router**

En `backend/src/pokedex/api/main.py`, importar `pokedex` desde `pokedex.api.routes` y añadir `app.include_router(pokedex.router)` junto al del catálogo.

- [ ] **Step 5: Correr y verificar que pasan**

Run: `cd backend && uv run pytest tests/api/test_pokedex_routes.py -v`
Expected: los 5 PASS

- [ ] **Step 6: Escribir el CLI del import**

`backend/src/pokedex/cli.py`:

```python
"""Comandos de línea de comandos.

    uv run python -m pokedex.cli import-excel ../Pokedex_Viviente_151.xlsx
"""

import argparse
import asyncio
import sys

import httpx

from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import TcgdexCatalog
from pokedex.config import settings
from pokedex.db import create_pool
from pokedex.wishlist.service import ImportService


async def _import_excel(path: str) -> int:
    pool = create_pool()
    pool.open()
    pool.wait()
    async with httpx.AsyncClient(timeout=30) as client:
        catalog = CatalogService(
            TcgdexCatalog(settings.tcgdex_base_url, client), pool.connection
        )
        summary = await ImportService(catalog, pool.connection).import_workbook(path)
    pool.close()
    print(
        f"Pokémon sembrados: {summary.pokemon}\n"
        f"Items creados: {summary.items_creados}\n"
        f"Items ya existentes: {summary.items_actualizados}\n"
        f"Opciones sin resolver: {summary.sin_resolver}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pokedex")
    sub = parser.add_subparsers(dest="command", required=True)
    importar = sub.add_parser("import-excel", help="siembra el checklist desde el Excel")
    importar.add_argument("path")
    args = parser.parse_args(argv)
    if args.command == "import-excel":
        return asyncio.run(_import_excel(args.path))
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

`CatalogService` cumple la forma que `OptionResolver` necesita salvo `list_set_cards`; añadirle un método pasante que delegue en el adaptador y espeje las cartas que traiga. Si al implementarlo resulta que `CatalogService` no expone `list_set_cards`, agregarlo ahí con un test en `tests/catalog/test_service.py` que verifique que delega y cachea.

- [ ] **Step 7: Correr el import real**

```bash
cd backend && uv run python -m pokedex.cli import-excel ../Pokedex_Viviente_151.xlsx
```

Expected: `Pokémon sembrados: 151`, items creados > 400, y un número bajo de opciones sin resolver. Esta corrida sí toca la red (espeja cartas de TCGdex) — es un comando manual, no un test.

- [ ] **Step 8: Verificar la data cargada**

```bash
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -c "
select count(*) as pokemon from app.pokemon;
select source_option, count(*), count(*) filter (where card_id is null) as sin_resolver
from app.wishlist_item group by source_option order by 1;
select count(*) as cartas_espejadas from app.card;"
```

Expected: 151 Pokémon; `opcion_1` y `opcion_2` con 151 cada una y cero sin resolver; `opcion_3` mayoritariamente resuelta; cientos de cartas espejadas.

- [ ] **Step 9: Suite completa y commit**

```bash
cd backend && uv run pytest -v && uv run ruff check . && uv run ruff format --check .
git add backend
git commit -m "feat: endpoints del pokedex y CLI de import"
```

---

## Verificación del plan completo

- [ ] `uv run pytest` pasa entero y sin red
- [ ] `GET /pokedex` devuelve 151 entradas
- [ ] `GET /pokedex/6` devuelve Charizard con sus opciones, cada una con imagen y precio cuando lo hay
- [ ] Reimportar el Excel no cambia el conteo de `wishlist_item`
- [ ] `app.wishlist_item` sigue siendo inalcanzable desde la Data API

## Qué queda fuera

- `mini_project` y sus miembros: el dashboard de mini-proyectos no es parte del entregable visible, y sembrarlos requiere decisiones de curaduría que no están en el Excel
- `owned_copy`, compras, prorrateo, captura y geolocalización: planes posteriores
- Edición de la wishlist desde la UI (agregar/quitar): el modelo lo soporta, los endpoints de escritura llegan cuando haya UI que los use
