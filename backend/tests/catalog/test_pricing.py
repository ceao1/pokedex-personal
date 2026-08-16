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
    assert extract_price_usd(variant) == Decimal("370.44")


def test_normal_lee_la_subclave_normal_y_no_la_de_reverse():
    variant = _variant("card_sv03.5-001", BULBASAUR_NORMAL)
    assert extract_price_usd(variant) == Decimal("0.25")


def test_reverse_lee_la_subclave_reverse_holofoil():
    """Mismo bloque `tcgplayer` que la normal, distinta sub-clave."""
    variant = _variant("card_sv03.5-001", BULBASAUR_REVERSE)
    assert extract_price_usd(variant) == Decimal("0.37")


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
