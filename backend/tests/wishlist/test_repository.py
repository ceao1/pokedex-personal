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
        insert into app.card (id, name, set_id, set_name, local_id, image_url, dex_number, raw)
        values (%s, %s, 'sv03.5', '151', '001', 'https://x/001/high.png', %s, '{}'::jsonb)
        on conflict do nothing
        """,
        (card_id, nombre, dex),
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


def test_list_pokedex_trae_la_carta_por_defecto_del_pokemon(clean_db):
    """La grilla del binder muestra el arte de la carta por defecto
    (`sv03.5-{dex:03d}`) sin que exista wishlist alguna: no hay Excel ni
    "ruta de caza" de la que depender, el catálogo ya sabe cuál es."""
    _sembrar_carta(clean_db)
    clean_db.execute(
        "update app.card set image_url = 'https://x/001/high.png' where id = 'sv03.5-001'"
    )
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["primary_image_url"] == "https://x/001/high.png"
    assert fila["primary_card_name"] == "Bulbasaur"


def test_list_pokedex_sin_carta_por_defecto_no_revienta(clean_db):
    """Antes del primer espejo de esa carta (`sembrar` sin red, o un
    Pokémon cuyo dex todavía no tiene fila en `app.card`), el bolsillo
    queda en `null`, nunca en un error."""
    repository.upsert_pokemon(clean_db, 1, "Bulbasaur")
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["primary_image_url"] is None
    assert fila["primary_card_name"] is None
    assert fila["primary_price_usd"] is None


def test_list_pokedex_ignora_la_wishlist_para_elegir_la_carta(clean_db):
    """La wishlist ya no decide qué carta se muestra -- solo la carta propia
    (si existe) o la carta por defecto. Un item de wishlist que apunta a
    otra carta más cara no debe robarle el bolsillo a la carta por
    defecto."""
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
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["primary_image_url"] == "https://x/001/high.png"
    assert fila["primary_card_name"] == "Bulbasaur"


def _sembrar_dos_variantes_del_mismo_tipo(conn, card_id="sv03.5-001"):
    """(card_id, type) no es único: Bulbasaur tiene una variante `normal`
    simple y otra con sello de set, ambas de type='normal'."""
    conn.execute(
        """
        insert into app.card_variant
          (id, card_id, type, stamp, price_usd, price_captured_at, raw)
        values
          (%(card_id)s || '-normal', %(card_id)s, 'normal', '{}', 0.10, now(), '{}'::jsonb),
          (%(card_id)s || '-normal-sello', %(card_id)s, 'normal', '{set-logo}', 28.00, now(),
           '{}'::jsonb)
        """,
        {"card_id": card_id},
    )


def test_list_wishlist_no_duplica_por_variantes_del_mismo_tipo(clean_db):
    """(card_id, type) no es único (ver `_sembrar_dos_variantes_del_mismo_tipo`);
    el join no debe multiplicar la fila del item."""
    _sembrar_carta(clean_db)
    _sembrar_dos_variantes_del_mismo_tipo(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    filas = repository.list_wishlist(clean_db)
    assert len(filas) == 1
    assert filas[0]["price_usd"] == Decimal("0.10"), "debe preferir la variante sin sello"


def test_list_pokedex_no_infla_el_conteo_por_variantes_del_mismo_tipo(clean_db):
    _sembrar_carta(clean_db)
    _sembrar_dos_variantes_del_mismo_tipo(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["wishlist_count"] == 1
    assert fila["primary_price_usd"] == Decimal("0.10")


def _sembrar_variante(conn, card_id, variant_id, *, tipo, subtype=None, stamp=None, precio="1.00"):
    conn.execute(
        """
        insert into app.card_variant (id, card_id, type, subtype, stamp, price_usd,
                                       price_captured_at, raw)
        values (%s, %s, %s, %s, %s, %s, now(), '{}'::jsonb)
        """,
        (variant_id, card_id, tipo, subtype, stamp or [], precio),
    )


def test_list_wishlist_resuelve_unlimited_por_subtype(clean_db):
    """`unlimited` vive en `subtype`, no en `type` (ver `catalog/variants.py`
    `_matches`); antes del fix, `v.type = w.variant_label` nunca encontraba
    nada para esta etiqueta."""
    _sembrar_carta(clean_db)
    _sembrar_variante(
        clean_db, "sv03.5-001", "sv03.5-001-unl", tipo="normal", subtype="unlimited", precio="5.00"
    )
    repository.upsert_wishlist_item(clean_db, _item(variant_label="unlimited"))
    fila = repository.list_wishlist(clean_db)[0]
    assert fila["price_usd"] == Decimal("5.00")


def test_list_wishlist_holo_exige_subtype_nulo(clean_db):
    """Mismo criterio que `_matches`: una variante `holo` con `subtype` no
    cuenta como el chip Holo (ese es el caso vintage, ver
    `test_el_chip_moderno_de_holo_no_matchea_vintage` en catalog)."""
    _sembrar_carta(clean_db)
    # El id de la variante con subtype (la que NO debe matchear) ordena
    # primero alfabéticamente a propósito: si el SQL no filtrara por
    # `subtype is null`, el `order by ... v.id` de desempate la elegiría
    # igual y el test pasaría por la razón equivocada.
    _sembrar_variante(
        clean_db,
        "sv03.5-001",
        "sv03.5-001-a-holo-vintage",
        tipo="holo",
        subtype="unlimited",
        precio="99.00",
    )
    _sembrar_variante(
        clean_db, "sv03.5-001", "sv03.5-001-z-holo", tipo="holo", subtype=None, precio="3.00"
    )
    repository.upsert_wishlist_item(clean_db, _item(variant_label="holo"))
    fila = repository.list_wishlist(clean_db)[0]
    assert fila["price_usd"] == Decimal("3.00")


def test_list_wishlist_shadowless_y_first_edition_no_se_solapan(clean_db):
    """`shadowless` exige que falte el sello '1st-edition'; una variante
    shadowless que SÍ trae ese sello debe resolver como `first_edition`,
    nunca como `shadowless` -- confundirlas sería un bug nuevo que el propio
    hallazgo advierte evitar."""
    _sembrar_carta(clean_db)
    _sembrar_variante(
        clean_db,
        "sv03.5-001",
        "sv03.5-001-shadowless",
        tipo="normal",
        subtype="shadowless",
        precio="10.00",
    )
    _sembrar_variante(
        clean_db,
        "sv03.5-001",
        "sv03.5-001-1st-shadowless",
        tipo="normal",
        subtype="shadowless",
        stamp=["1st-edition"],
        precio="500.00",
    )
    repository.upsert_wishlist_item(clean_db, _item(variant_label="shadowless"))
    repository.upsert_wishlist_item(
        clean_db, _item(variant_label="first_edition", source_option="opcion_2")
    )
    filas = {f["variant_label"]: f for f in repository.list_wishlist(clean_db)}
    assert filas["shadowless"]["price_usd"] == Decimal("10.00")
    assert filas["first_edition"]["price_usd"] == Decimal("500.00")


def test_list_pokedex_salta_una_variante_sin_precio(clean_db):
    """Si la variante menos exótica de la carta elegida no tiene precio
    capturado, no hay que devolver `null` habiendo una variante con precio
    real: eso restaría en silencio a "Completar el 151". La variante sin
    sello ni foil no tiene precio; la que sí lo tiene queda en segundo lugar
    por especificidad, pero gana igual porque está priceada."""
    _sembrar_carta(clean_db)
    clean_db.execute(
        """
        insert into app.card_variant (id, card_id, type, price_usd, price_captured_at, raw)
        values ('sv03.5-001-sin-precio', 'sv03.5-001', 'normal', null, null, '{}'::jsonb)
        """
    )
    _sembrar_variante(
        clean_db,
        "sv03.5-001",
        "sv03.5-001-con-sello",
        tipo="normal",
        stamp=["set-logo"],
        precio="28.00",
    )
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["primary_price_usd"] == Decimal("28.00")


def test_list_pokedex_el_precio_y_su_fecha_vienen_de_la_misma_variante(clean_db):
    """`primary_price_usd` y `primary_price_captured_at` deben describir la
    misma variante -- si no, la fecha mostrada podría corresponder a un
    precio distinto del que ve el usuario."""
    _sembrar_carta(clean_db)
    _sembrar_variante(clean_db, "sv03.5-001", "sv03.5-001-normal", tipo="normal", precio="0.10")
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["primary_price_usd"] == Decimal("0.10")
    assert fila["primary_price_captured_at"] is not None


def test_owned_count_es_cero_mientras_no_haya_captura(clean_db):
    """El contador del dashboard no puede mentir sobre lo que se posee.
    Sin ejemplares capturados en `app.owned_copy`, la respuesta honesta es cero."""
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["owned_count"] == 0


def test_owned_count_cuenta_ejemplares_reales(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["owned_count"] == 0

    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id)
        values ('66666666-6666-6666-6666-666666666666', 'sv03.5-001')
        """
    )
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["owned_count"] == 1


def test_una_carta_vendida_no_cuenta_como_conseguida(clean_db):
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, lifecycle_status)
        values ('77777777-7777-7777-7777-777777777777', 'sv03.5-001', 'vendida')
        """
    )
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["owned_count"] == 0


def test_el_bolsillo_muestra_tu_carta_cuando_la_tienes(clean_db):
    """Con la carta en la mano ya no persigues nada: el bolsillo enseña la tuya."""
    from uuid import uuid4

    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    clean_db.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, dex_number, image_url, raw)
        values ('base1-44', 'Bulbasaur', 'base1', 'Base Set', '44', 1,
                'https://x/base/44/high.png', '{}'::jsonb)
        """
    )
    clean_db.execute(
        "insert into app.owned_copy (client_draft_id, card_id) values (%s, 'base1-44')",
        (uuid4(),),
    )
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["primary_image_url"] == "https://x/base/44/high.png"
    assert fila["owned_count"] == 1


def test_dos_ejemplares_de_la_misma_carta_cuentan_dos(clean_db):
    """Un duplicado es un ejemplar más, no un Pokémon más — el progreso del
    151 se calcula sobre Pokémon distintos, no sobre este conteo."""
    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    for uuid_ in ("88888888-8888-8888-8888-888888888888", "99999999-9999-9999-9999-999999999999"):
        clean_db.execute(
            "insert into app.owned_copy (client_draft_id, card_id) values (%s, 'sv03.5-001')",
            (uuid_,),
        )
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["owned_count"] == 2
