import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from psycopg.rows import dict_row

# --------------------------------------------------------------------------
# Base de datos dedicada para tests
# --------------------------------------------------------------------------
# El defecto más destructivo de este proyecto: los tests y la app corrida
# compartían una sola base de datos, así que cada corrida de la suite
# vaciaba la colección real del dueño (`app.owned_copy`). Lo de abajo le da
# a los tests su propia base, en el mismo Postgres local de Supabase, para
# que `uv run pytest` no pueda tocar jamás la base que sirve la app.
#
# `_DEV_DATABASE_URL` es la base de desarrollo real -- la que usa la app y
# la que jamás debe truncarse -- y sirve dos propósitos: es la base de
# mantenimiento contra la que se emite `create database` (una operación de
# catálogo, no toca filas de `postgres`) y es el valor contra el que se
# compara el candado de seguridad de más abajo.
_DEV_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
_TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54322/pokedex_test"

# Se fija ANTES de importar `pokedex.config`, que lee la variable de entorno
# una sola vez al importarse (`Settings()` se instancia al nivel de módulo).
# `setdefault` respeta un `DATABASE_URL` ya exportado -- así se puede probar
# el candado de seguridad de más abajo apuntando a propósito a la base de
# desarrollo -- y si no hay nada exportado, apunta acá por defecto: un
# checkout nuevo no necesita ningún paso manual.
os.environ.setdefault("DATABASE_URL", _TEST_DATABASE_URL)

from pokedex.config import settings  # noqa: E402  (después de fijar DATABASE_URL)

_BASE_DE_DESARROLLO = urlsplit(_DEV_DATABASE_URL).path.lstrip("/")

# Esta migración inserta una fila en `storage.buckets`, tabla que solo
# existe en el stack completo de Supabase (la crea el servicio storage-api),
# no en una base Postgres común. La base de tests no corre ese servicio --
# todo lo que toca Storage se mockea por HTTP, ver
# `tests/collection/test_storage.py` -- así que esta única migración no
# aplica acá y se salta a propósito, por nombre explícito, para que quede
# claro cuál es y por qué. El resto de las migraciones corre sin cambios:
# el esquema de tests viene de las migraciones reales, nunca de una copia
# mantenida a mano.
_MIGRACIONES_SOLO_PLATAFORMA = {"20260816034536_create_storage_bucket"}


def _prohibir_base_de_desarrollo(dbname: str) -> None:
    """Candado de seguridad: corta de raíz si algo apunta a la base de desarrollo.

    Tiene que fallar fuerte y con un mensaje claro -- nunca un skip
    silencioso, que escondería el problema en vez de impedirlo -- y tiene
    que seguir funcionando aunque alguien más adelante "simplifique" el
    resto de este archivo.
    """
    if dbname == _BASE_DE_DESARROLLO:
        raise RuntimeError(
            "Los tests están apuntando a la base de datos de DESARROLLO "
            f"({dbname!r}), la misma que sirve la app real: esto truncaría "
            "la colección real del dueño. Configura DATABASE_URL apuntando "
            f"a una base de tests dedicada (por defecto {_TEST_DATABASE_URL!r}) "
            "antes de ejecutar los tests de nuevo."
        )


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def _crear_base_de_test_si_falta(test_db_name: str) -> None:
    with psycopg.connect(_DEV_DATABASE_URL, autocommit=True) as conn:
        existe = conn.execute(
            "select 1 from pg_database where datname = %s", (test_db_name,)
        ).fetchone()
        if not existe:
            conn.execute(f'create database "{test_db_name}"')


def _migrar_base_de_test(test_dsn: str) -> None:
    with psycopg.connect(test_dsn, autocommit=True) as conn:
        conn.execute("create schema if not exists supabase_migrations")
        conn.execute(
            "create table if not exists supabase_migrations.schema_migrations "
            "(version text primary key)"
        )
        aplicadas = {
            fila[0]
            for fila in conn.execute(
                "select version from supabase_migrations.schema_migrations"
            ).fetchall()
        }
        for path in sorted(_migrations_dir().glob("*.sql")):
            version = path.stem
            sql = path.read_text()
            if version in _MIGRACIONES_SOLO_PLATAFORMA:
                # Guarda la premisa de la lista de arriba: es solo para
                # migraciones de plataforma (storage/auth), nunca para
                # esquema de aplicación. Si alguien agrega ahí una migración
                # que sí toca `app.*` para esquivar un error de
                # `DuplicateTable` u otro, la base de tests quedaría con un
                # esquema que la app no tiene -- justo lo que el punto 3 de
                # los requisitos pide evitar. Esto lo hace imposible en vez
                # de confiar en que nadie se equivoque.
                if "app." in sql or "app " in sql:
                    raise RuntimeError(
                        f"{version!r} está en _MIGRACIONES_SOLO_PLATAFORMA pero "
                        "su SQL menciona el esquema `app`: saltarla dejaría la "
                        "base de tests con un esquema que la app no tiene. Esa "
                        "lista es solo para migraciones de plataforma "
                        "(storage/auth), nunca para esquema de aplicación."
                    )
                continue
            if version in aplicadas:
                continue
            with conn.transaction():
                conn.execute(sql)
                conn.execute(
                    "insert into supabase_migrations.schema_migrations (version) values (%s)",
                    (version,),
                )


def pytest_configure(config: pytest.Config) -> None:
    """Crea y migra la base de datos de tests, una sola vez por sesión.

    Corre antes de que se recolecte un solo test, así que un checkout nuevo
    funciona con solo `uv run pytest`: si la base no existe, se crea; si le
    faltan migraciones, se aplican. Si ya existe y está al día -- el caso
    normal -- esto es un par de queries triviales, no una reconstrucción de
    esquema por corrida.
    """
    partes = urlsplit(settings.database_url)
    test_db_name = partes.path.lstrip("/")
    _prohibir_base_de_desarrollo(test_db_name)
    _crear_base_de_test_si_falta(test_db_name)
    _migrar_base_de_test(settings.database_url)


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


@pytest.fixture()
def db_conn():
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        _prohibir_base_de_desarrollo(conn.info.dbname)
        yield conn
        conn.rollback()


_TRUNCATE = (
    "truncate app.card, app.pokemon, app.wishlist_item, app.owned_copy, app.binder, "
    "app.purchase cascade"
)


@pytest.fixture()
def clean_db(db_conn):
    _prohibir_base_de_desarrollo(db_conn.info.dbname)
    db_conn.execute(_TRUNCATE)
    db_conn.commit()
    yield db_conn
    # Trunca también al final: si no, lo que el último test dejó commiteado
    # (ej. `conn.commit()` dentro de un `SeedService.sembrar`) sobrevive a
    # `db_conn`'s rollback-on-exit y contamina la próxima corrida de la
    # suite completa.
    #
    # Si el test dejó la transacción abortada (ej. probó una violación de
    # constraint con `pytest.raises` sin volver a hacer rollback), el
    # truncate de abajo fallaría con `InFailedSqlTransaction`: se hace
    # rollback primero, que es un no-op si la transacción ya estaba limpia.
    db_conn.rollback()
    db_conn.execute(_TRUNCATE)
    db_conn.commit()
