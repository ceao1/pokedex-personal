from decimal import Decimal

from pokedex.wishlist import repository
from pokedex.wishlist.models import WishlistItemIn


def _sembrar_carta(conn, card_id="sv03.5-001", dex=1, nombre="Bulbasaur"):
    conn.execute(
        "insert into app.pokemon (dex_number, name) values (%s, %s) on conflict do nothing",
        (dex, nombre),
    )
    conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, image_url, raw)
        values (%s, %s, 'sv03.5', '151', '001', 'https://x/001/high.png', '{}'::jsonb)
        on conflict do nothing
        """,
        (card_id, nombre),
    )


def _item(**kwargs):
    base = dict(
        dex_number=1,
        card_id="sv03.5-001",
        variant_label="normal",
        raw_text="Bulbasaur 001/165",
        source_option="opcion_1",
        auto_resolved=False,
        is_favorite=False,
        reference_value_usd=Decimal("0.15"),
    )
    base.update(kwargs)
    return WishlistItemIn(**base)


def test_upsert_crea_el_item(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    filas = repository.list_wishlist(clean_db)
    assert len(filas) == 1
    assert filas[0]["card_id"] == "sv03.5-001"


def test_reimportar_no_duplica(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    repository.upsert_wishlist_item(clean_db, _item())
    assert len(repository.list_wishlist(clean_db)) == 1


def test_la_misma_carta_en_dos_variantes_son_dos_items(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item(variant_label="normal"))
    repository.upsert_wishlist_item(
        clean_db, _item(variant_label="reverse", source_option="opcion_2")
    )
    assert len(repository.list_wishlist(clean_db)) == 2


def test_el_reimport_no_pisa_una_correccion_manual(clean_db):
    """auto_resolved=false significa que el humano ya lo revisó."""
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item(auto_resolved=True))
    clean_db.execute("update app.wishlist_item set auto_resolved = false, card_id = 'sv03.5-001'")
    repository.upsert_wishlist_item(clean_db, _item(auto_resolved=True))
    fila = repository.list_wishlist(clean_db)[0]
    assert fila["auto_resolved"] is False


def test_reimportar_actualiza_precio_y_texto_de_un_item_resuelto(clean_db):
    """Un `DO NOTHING` pasaría los tests de conteo pero dejaría precios
    viejos; hay que probar que los valores realmente se refrescan."""
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    repository.upsert_wishlist_item(
        clean_db,
        _item(reference_value_usd=Decimal("9.99"), raw_text="Bulbasaur 001/165 (actualizado)"),
    )
    filas = repository.list_wishlist(clean_db)
    assert len(filas) == 1
    assert filas[0]["reference_value_usd"] == Decimal("9.99")
    assert filas[0]["raw_text"] == "Bulbasaur 001/165 (actualizado)"


def test_reimportar_actualiza_el_precio_de_un_item_sin_resolver(clean_db):
    clean_db.execute("insert into app.pokemon (dex_number, name) values (9, 'Blastoise')")
    sin_resolver = dict(
        dex_number=9,
        card_id=None,
        variant_label=None,
        raw_text="Blastoise Base Set",
        source_option="opcion_3",
    )
    repository.upsert_wishlist_item(clean_db, _item(**sin_resolver))
    repository.upsert_wishlist_item(
        clean_db, _item(**sin_resolver, reference_value_usd=Decimal("42.00"))
    )
    filas = repository.list_wishlist(clean_db)
    assert len(filas) == 1
    assert filas[0]["reference_value_usd"] == Decimal("42.00")


def test_los_items_sin_resolver_se_guardan_con_su_texto(clean_db):
    clean_db.execute("insert into app.pokemon (dex_number, name) values (9, 'Blastoise')")
    repository.upsert_wishlist_item(
        clean_db,
        _item(
            dex_number=9,
            card_id=None,
            variant_label=None,
            raw_text="Blastoise Base Set",
            source_option="opcion_3",
        ),
    )
    fila = repository.list_wishlist(clean_db)[0]
    assert fila["card_id"] is None
    assert fila["raw_text"] == "Blastoise Base Set"


def test_reimportar_un_item_sin_resolver_tampoco_duplica(clean_db):
    clean_db.execute("insert into app.pokemon (dex_number, name) values (9, 'Blastoise')")
    item = _item(
        dex_number=9,
        card_id=None,
        variant_label=None,
        raw_text="Blastoise Base Set",
        source_option="opcion_3",
    )
    repository.upsert_wishlist_item(clean_db, item)
    repository.upsert_wishlist_item(clean_db, item)
    assert len(repository.list_wishlist(clean_db)) == 1


def test_list_pokedex_devuelve_los_sembrados_con_su_conteo(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_pokemon(clean_db, 2, "Ivysaur")
    repository.upsert_wishlist_item(clean_db, _item())
    filas = {f["dex_number"]: f for f in repository.list_pokedex(clean_db)}
    assert filas[1]["name"] == "Bulbasaur"
    assert filas[1]["wishlist_count"] == 1
    assert filas[2]["wishlist_count"] == 0


def test_list_pokedex_trae_la_carta_de_la_ruta_preferida(clean_db):
    """La grilla del binder muestra el arte real de la carta que se persigue."""
    _sembrar_carta(clean_db)
    clean_db.execute(
        "update app.card set image_url = 'https://x/001/high.png' where id = 'sv03.5-001'"
    )
    repository.upsert_wishlist_item(clean_db, _item())
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["primary_image_url"] == "https://x/001/high.png"
    assert fila["primary_card_name"] == "Bulbasaur"


def test_la_ruta_preferida_es_la_opcion_1_y_no_otra(clean_db):
    """Con varias opciones resueltas gana la económica del set 151."""
    _sembrar_carta(clean_db)
    clean_db.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, image_url, raw)
        values ('sv03.5-166', 'Bulbasaur IR', 'sv03.5', '151', '166',
                'https://x/166/high.png', '{}'::jsonb)
        """
    )
    repository.upsert_wishlist_item(
        clean_db, _item(source_option="opcion_2", card_id="sv03.5-166", variant_label="holo")
    )
    repository.upsert_wishlist_item(clean_db, _item(source_option="opcion_1"))
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert (
        fila["primary_image_url"] == "https://x/001/high.png"
        or fila["primary_card_name"] == "Bulbasaur"
    )


def test_owned_count_es_cero_mientras_no_haya_captura(clean_db):
    """El contador del dashboard no puede mentir sobre lo que se posee.
    `app.owned_copy` no existe todavía, así que la respuesta honesta es cero."""
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["owned_count"] == 0
