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
