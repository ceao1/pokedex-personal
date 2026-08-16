"""Los 151 están en el código, así que los vigila un test y no un archivo.

Estas comprobaciones no son ceremonia: la lista se generó desde una fuente
externa una sola vez, y a partir de ahí nadie va a volver a mirarla. Un dedo
torpe que borre una línea dejaría 150 casilleros y el fallo aparecería como
"me falta un Pokémon" semanas después.
"""

from pokedex.catalog.pokemon_151 import NOMBRES_151, los_151

# Anclas del Pokédex Nacional. Son hechos públicos desde 1996 y no cambian.
ANCLAS = {
    1: "Bulbasaur",
    4: "Charmander",
    6: "Charizard",
    7: "Squirtle",
    25: "Pikachu",
    29: "Nidoran♀",
    32: "Nidoran♂",
    44: "Gloom",
    # Farfetch'd lleva apóstrofo en las cartas. PokeAPI lo quita, y esa
    # diferencia se coló en la primera versión de la lista: la detectó
    # comparar contra los nombres reales del set sv03.5, no este test.
    83: "Farfetch'd",
    122: "Mr. Mime",
    150: "Mewtwo",
    151: "Mew",
}


def test_son_exactamente_ciento_cincuenta_y_uno():
    assert len(NOMBRES_151) == 151


def test_las_anclas_estan_en_su_numero():
    for numero, nombre in ANCLAS.items():
        assert NOMBRES_151[numero - 1] == nombre, f"el {numero} debería ser {nombre}"


def test_no_hay_nombres_repetidos():
    assert len(set(NOMBRES_151)) == 151


def test_ningun_nombre_esta_vacio_ni_con_espacios_de_sobra():
    for nombre in NOMBRES_151:
        assert nombre and nombre == nombre.strip()


def test_los_151_devuelve_pares_numerados_del_1_al_151():
    pares = los_151()
    assert len(pares) == 151
    assert pares[0] == (1, "Bulbasaur")
    assert pares[-1] == (151, "Mew")
    assert [n for n, _ in pares] == list(range(1, 152))


def test_la_grafia_especial_es_la_del_tcg():
    """`Nidoran♀`, `Nidoran♂` y `Mr. Mime` se escriben así en las cartas.

    Emparejar por nombre contra el catálogo depende de respetarlo: un
    `Nidoran F` o un `Mr Mime` no encontrarían su carta. Verificado contra
    los sets base1, base2 y sv03.5 de TCGdex.
    """
    assert "Nidoran♀" in NOMBRES_151
    assert "Nidoran♂" in NOMBRES_151
    assert "Mr. Mime" in NOMBRES_151
    assert not any(n.startswith("Mr-") or n.endswith("-f") or n.endswith("-m") for n in NOMBRES_151)
