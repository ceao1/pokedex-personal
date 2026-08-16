from datetime import UTC, datetime
from decimal import Decimal

from pokedex.catalog import repository
from pokedex.catalog.tcgdex import parse_card

from .loaders import load_fixture

CAPTURED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def test_upsert_guarda_la_carta_y_sus_variantes(clean_db):
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    repository.upsert_card(clean_db, card)

    recuperada = repository.get_card(clean_db, "sv03.5-001")
    assert recuperada is not None
    assert recuperada.name == "Bulbasaur"
    assert recuperada.dex_number == 1
    assert len(recuperada.variants) == len(card.variants)


def test_upsert_conserva_el_precio_por_variante(clean_db):
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    repository.upsert_card(clean_db, card)

    recuperada = repository.get_card(clean_db, "sv03.5-001")
    por_id = {v.id: v for v in recuperada.variants}
    original = {v.id: v for v in card.variants}
    for variant_id, esperada in original.items():
        assert por_id[variant_id].price_usd == esperada.price_usd


def test_upsert_es_idempotente(clean_db):
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    repository.upsert_card(clean_db, card)
    repository.upsert_card(clean_db, card)

    total = clean_db.execute(
        "select count(*) as n from app.card_variant where card_id = 'sv03.5-001'"
    ).fetchone()["n"]
    assert total == len(card.variants)


def test_upsert_actualiza_el_precio_al_refrescar(clean_db):
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    repository.upsert_card(clean_db, card)

    con_precio = next(v for v in card.variants if v.price_usd is not None)
    con_precio.price_usd = Decimal("9.99")
    repository.upsert_card(clean_db, card)

    recuperada = repository.get_card(clean_db, "sv03.5-001")
    actualizada = next(v for v in recuperada.variants if v.id == con_precio.id)
    assert actualizada.price_usd == Decimal("9.99")


def test_get_card_devuelve_none_si_no_esta(clean_db):
    assert repository.get_card(clean_db, "no-existe") is None


def test_find_by_set_and_number(clean_db):
    card = parse_card(load_fixture("card_sv03.5-001"), CAPTURED_AT)
    repository.upsert_card(clean_db, card)

    encontrada = repository.find_by_set_and_number(clean_db, "sv03.5", "001")
    assert encontrada is not None
    assert encontrada.id == "sv03.5-001"
    assert repository.find_by_set_and_number(clean_db, "sv03.5", "999") is None
