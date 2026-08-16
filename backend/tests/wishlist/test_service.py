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
    """Restricción global: la columna ✔ del Excel se ignora por completo.

    `app.owned_copy` no existe en ningún plan ejecutado todavía (llega con el
    plan de captura). Este test se deja en skip, con la tabla nombrada
    explícitamente, para que se vuelva un test real y ejecutable el día que
    esa tabla exista — mientras tanto la restricción sigue cubierta por
    `test_la_columna_de_check_se_ignora` en `tests/wishlist/test_excel.py`.
    """
    pytest.skip("app.owned_copy no existe todavía (plan de captura pendiente)")
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
