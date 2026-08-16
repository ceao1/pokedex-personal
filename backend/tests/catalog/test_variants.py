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
    assert holo.price_usd == Decimal("370.44")
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
    assert elegida.price_usd == Decimal("0.37")


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
