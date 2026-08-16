"""Los 151 del código contra el set 151 de TCGdex, que es la autoridad real.

Excluido de la suite por defecto (marca `contract`). Correr a mano:
    uv run pytest -m contract -v

Este test existe porque encontró un fallo que las anclas escritas a mano no
vieron: el dex 83 estaba como `Farfetchd` en vez de `Farfetch'd`, porque la
fuente de la que se generó la lista quita los apóstrofos. Un nombre mal
escrito rompe el emparejamiento con el catálogo en silencio — la carta
simplemente no aparece — así que comparar contra los nombres impresos de
verdad vale más que cualquier ancla que a uno se le ocurra.

De paso fija la otra propiedad de la que depende la imagen por defecto de
cada bolsillo: en el set `sv03.5` el número de carta 001..151 **es** el
número de dex.
"""

import httpx
import pytest

from pokedex.catalog.pokemon_151 import NOMBRES_151

pytestmark = pytest.mark.contract

SET_151 = "sv03.5"


@pytest.fixture(scope="module")
def cartas_del_set() -> dict[str, str]:
    respuesta = httpx.get(f"https://api.tcgdex.net/v2/en/sets/{SET_151}", timeout=30)
    respuesta.raise_for_status()
    return {c["localId"]: c["name"] for c in respuesta.json()["cards"]}


def _sin_sufijo_ex(nombre: str) -> str:
    """El set imprime `Charizard ex` en el 006; el Pokémon sigue siendo Charizard."""
    return nombre[:-3] if nombre.endswith(" ex") else nombre


def test_los_151_nombres_coinciden_con_los_impresos_en_las_cartas():
    respuesta = httpx.get(f"https://api.tcgdex.net/v2/en/sets/{SET_151}", timeout=30)
    respuesta.raise_for_status()
    por_numero = {c["localId"]: c["name"] for c in respuesta.json()["cards"]}

    discrepancias = []
    for dex, nuestro in enumerate(NOMBRES_151, start=1):
        impreso = por_numero.get(f"{dex:03d}")
        if impreso is None:
            discrepancias.append(f"dex {dex}: el set no tiene la carta {dex:03d}")
        elif _sin_sufijo_ex(impreso) != nuestro:
            discrepancias.append(f"dex {dex}: tenemos {nuestro!r}, la carta dice {impreso!r}")

    assert not discrepancias, "los nombres se desviaron del catálogo:\n" + "\n".join(discrepancias)


def test_el_numero_de_carta_es_el_numero_de_dex(cartas_del_set: dict[str, str]):
    """La imagen por defecto de cada bolsillo depende de esta propiedad.

    Si TCGdex renumerara el set, `sv03.5-044` dejaría de ser Gloom y todos
    los bolsillos mostrarían la carta equivocada sin que nada falle.
    """
    for dex in (1, 44, 100, 151):
        impreso = cartas_del_set[f"{dex:03d}"]
        assert _sin_sufijo_ex(impreso) == NOMBRES_151[dex - 1]
