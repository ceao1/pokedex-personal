from contextlib import contextmanager
from pathlib import Path

import pytest
from openpyxl import Workbook

from pokedex.catalog.models import Card
from pokedex.catalog.service import CatalogService
from pokedex.wishlist import repository
from pokedex.wishlist.excel import SHEET_DEX, SHEET_GALLERY
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


class FakeCatalogPortConNumeros:
    """Puerto falso que sí resuelve números fijos del set 151, para probar
    que la galería encuentra y marca la misma carta que ya resolvió una
    opción, en vez de crear una fila nueva."""

    def __init__(self, cartas: dict[str, str]):
        self._cartas = cartas  # local_id -> card_id

    async def get_card(self, card_id: str):
        return None

    async def find_by_set_and_number(self, set_id: str, local_id: str):
        card_id = self._cartas.get(local_id) if set_id == "sv03.5" else None
        if card_id is None:
            return None
        return Card(
            id=card_id, name="Ditto", set_id=set_id, set_name="151", local_id=local_id, raw={}
        )

    async def list_set_cards(self, set_id: str):
        return []


def _build_mini_workbook(tmp_path: Path) -> Path:
    """Un Pokémon con opción 1 (001/165) y opción 2 (166/165, no-reverse:
    una Illustration Rare propia), más una fila de galería que la nombra por
    el mismo número — el caso real es "Bulbasaur 151 166/165"."""
    workbook = Workbook()
    dex_sheet = workbook.active
    dex_sheet.title = SHEET_DEX
    dex_sheet["A4"] = 1
    dex_sheet["B4"] = "Ditto"
    dex_sheet["E4"] = "Ditto 001/165"
    dex_sheet["G4"] = "0.10"
    dex_sheet["I4"] = "Ditto 166/165"
    dex_sheet["K4"] = "12.00"

    gallery_sheet = workbook.create_sheet(SHEET_GALLERY)
    gallery_sheet["A4"] = 1
    gallery_sheet["B4"] = "Ditto"
    gallery_sheet["C4"] = "Ditto 151 166/165"
    gallery_sheet["D4"] = "12.00"

    path = tmp_path / "mini.xlsx"
    workbook.save(path)
    return path


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


async def test_la_galeria_marca_favoritos_en_vez_de_duplicar(conn_factory, clean_db, tmp_path):
    """Cuando la galería resuelve a la misma carta que ya insertó una opción,
    no debe crear una fila nueva: debe marcar `is_favorite` en la existente."""
    path = _build_mini_workbook(tmp_path)
    port = FakeCatalogPortConNumeros({"001": "sv03.5-001", "166": "sv03.5-166"})
    catalog = CatalogService(port, conn_factory)
    service = ImportService(catalog, conn_factory)

    await service.import_workbook(path)

    filas = repository.list_wishlist(clean_db, dex_number=1)
    assert len(filas) == 2, "la galería no debe agregar una fila además de opción 1 y 2"
    opcion_2 = next(f for f in filas if f["card_id"] == "sv03.5-166")
    assert opcion_2["is_favorite"] is True


async def test_la_galeria_marca_favorita_una_fila_sin_resolver_cuando_el_texto_no_resuelve(
    conn_factory, clean_db
):
    """Trece filas de la galería dicen literalmente 'Ya está en tu Opción 2':
    no traen número, así que no hay con qué fusionar. Deben seguir quedando
    como una fila propia, marcada como favorita."""
    service = ImportService(FakeCatalogService(clean_db), conn_factory)
    await service.import_workbook(XLSX)
    favoritos_sin_resolver = clean_db.execute(
        "select count(*) as n from app.wishlist_item"
        " where is_favorite and card_id is null and source_option = 'galeria'"
    ).fetchone()["n"]
    assert favoritos_sin_resolver > 0
