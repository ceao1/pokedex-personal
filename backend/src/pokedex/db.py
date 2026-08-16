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
