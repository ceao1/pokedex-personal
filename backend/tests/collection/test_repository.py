from decimal import Decimal
from uuid import UUID

from pokedex.collection import repository
from pokedex.collection.models import OwnedCopyIn
from pokedex.wishlist import repository as wishlist_repository


def test_crear_borrador_dos_veces_no_duplica(clean_db):
    draft = UUID("aaaaaaaa-0000-0000-0000-000000000001")
    primero = repository.crear_borrador(clean_db, draft)
    segundo = repository.crear_borrador(clean_db, draft)
    assert primero.id == segundo.id
    total = clean_db.execute("select count(*) as n from app.owned_copy").fetchone()["n"]
    assert total == 1


def test_el_patch_solo_toca_los_campos_enviados(clean_db):
    draft = UUID("aaaaaaaa-0000-0000-0000-000000000002")
    repository.crear_borrador(clean_db, draft)
    repository.actualizar(clean_db, draft, OwnedCopyIn(condition="NM", notes="ejemplo"))
    repository.actualizar(clean_db, draft, OwnedCopyIn(condition="LP"))
    fila = repository.obtener(clean_db, draft)
    assert fila.condition == "LP"
    assert fila.notes == "ejemplo", "un PATCH parcial no puede borrar lo que no menciona"


def test_un_patch_vacio_no_revienta(clean_db):
    draft = UUID("aaaaaaaa-0000-0000-0000-000000000003")
    repository.crear_borrador(clean_db, draft)
    assert repository.actualizar(clean_db, draft, OwnedCopyIn()) is not None


def test_actualizar_un_borrador_inexistente_devuelve_none(clean_db):
    draft = UUID("aaaaaaaa-0000-0000-0000-000000000004")
    assert repository.actualizar(clean_db, draft, OwnedCopyIn(condition="NM")) is None


def test_obtener_un_borrador_inexistente_devuelve_none(clean_db):
    draft = UUID("aaaaaaaa-0000-0000-0000-000000000005")
    assert repository.obtener(clean_db, draft) is None


def test_guardar_fotos_persiste_ambos_paths(clean_db):
    draft = UUID("aaaaaaaa-0000-0000-0000-000000000006")
    repository.crear_borrador(clean_db, draft)
    repository.guardar_fotos(clean_db, draft, "aaaaaaaa.../front.jpg", "aaaaaaaa.../thumb.jpg")
    fila = repository.obtener(clean_db, draft)
    assert fila.photo_front_url == "aaaaaaaa.../front.jpg"
    assert fila.photo_thumb_url == "aaaaaaaa.../thumb.jpg"


def test_listar_pendientes_excluye_los_listos(clean_db):
    listo = UUID("aaaaaaaa-0000-0000-0000-000000000007")
    pendiente = UUID("aaaaaaaa-0000-0000-0000-000000000008")
    repository.crear_borrador(clean_db, listo)
    repository.crear_borrador(clean_db, pendiente)
    repository.actualizar(clean_db, listo, OwnedCopyIn(capture_status="listo"))

    pendientes = repository.listar_pendientes(clean_db)
    ids = {c.client_draft_id for c in pendientes}
    assert pendiente in ids
    assert listo not in ids


def _sembrar_pokemon_y_carta(conn, dex, card_id, nombre, local_id):
    conn.execute(
        "insert into app.pokemon (dex_number, name) values (%s, %s) on conflict do nothing",
        (dex, nombre),
    )
    conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, dex_number, image_url, raw)
        values (%s, %s, 'sv03.5', '151', %s, %s, %s, '{}'::jsonb)
        on conflict do nothing
        """,
        (card_id, nombre, local_id, dex, f"https://x/{local_id}/high.png"),
    )


def test_listar_por_dex_devuelve_los_ejemplares_de_ese_pokemon(clean_db):
    from uuid import uuid4

    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    _sembrar_pokemon_y_carta(clean_db, 1, "sv03.5-001", "Bulbasaur", "001")
    for card_id in ("sv03.5-004", "sv03.5-004", "sv03.5-001"):
        clean_db.execute(
            "insert into app.owned_copy (client_draft_id, card_id) values (%s, %s)",
            (uuid4(), card_id),
        )

    charmanders = repository.listar_por_dex(clean_db, 4)
    assert len(charmanders) == 2, "dos ejemplares del mismo Pokémon son dos, no uno"
    assert {c["card_id"] for c in charmanders} == {"sv03.5-004"}
    assert len(repository.listar_por_dex(clean_db, 1)) == 1


def test_dos_impresiones_distintas_del_mismo_pokemon_conviven(clean_db):
    """El caso que pidió el dueño: varios Charmander de sets distintos."""
    from uuid import uuid4

    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    _sembrar_pokemon_y_carta(clean_db, 4, "base1-46", "Charmander", "46")
    for card_id in ("sv03.5-004", "base1-46"):
        clean_db.execute(
            "insert into app.owned_copy (client_draft_id, card_id) values (%s, %s)",
            (uuid4(), card_id),
        )

    ejemplares = repository.listar_por_dex(clean_db, 4)
    assert {e["card_id"] for e in ejemplares} == {"sv03.5-004", "base1-46"}
    assert {e["set_name"] for e in ejemplares} == {"151"}


def test_una_carta_vendida_no_aparece_entre_tus_ejemplares(clean_db):
    from uuid import uuid4

    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, lifecycle_status)
        values (%s, 'sv03.5-004', 'vendida')
        """,
        (uuid4(),),
    )
    assert repository.listar_por_dex(clean_db, 4) == []


def test_los_ejemplares_traen_lo_necesario_para_dibujarlos(clean_db):
    from uuid import uuid4

    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    clean_db.execute(
        """
        insert into app.owned_copy
          (client_draft_id, card_id, condition, purchase_price_usd, photo_front_url, notes)
        values (%s, 'sv03.5-004', 'NM', 1.50, 'abc/front.jpg', 'de la tienda de Miraflores')
        """,
        (uuid4(),),
    )
    ejemplar = repository.listar_por_dex(clean_db, 4)[0]
    for campo in (
        "id",
        "card_id",
        "card_name",
        "set_name",
        "image_url",
        "condition",
        "purchase_price_usd",
        "photo_front_url",
        "notes",
        "created_at",
    ):
        assert campo in ejemplar, f"falta {campo}"


def test_listar_por_dex_muestra_el_costo_asignado_por_una_compra_no_el_precio_suelto(clean_db):
    """El costo que muestra la ficha es el que decide `app.owned_copy_costo`
    (task de compras), no la columna `purchase_price_usd` cruda: un ejemplar
    que salió de un reparto tiene que mostrar lo que el reparto le asignó."""
    from decimal import Decimal
    from uuid import uuid4

    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, purchase_price_usd, assigned_cost_usd)
        values (%s, 'sv03.5-004', 9.99, 3.33)
        """,
        (uuid4(),),
    )
    ejemplar = repository.listar_por_dex(clean_db, 4)[0]
    assert ejemplar["purchase_price_usd"] == Decimal("3.33")


def test_obtener_expone_purchase_id_assigned_cost_e_is_bulk(clean_db):
    draft = UUID("aaaaaaaa-0000-0000-0000-00000000000a")
    compra = clean_db.execute(
        "insert into app.purchase (source_type, total_usd) values ('lote', 10.00) returning id"
    ).fetchone()
    repository.crear_borrador(clean_db, draft)
    clean_db.execute(
        """
        update app.owned_copy
        set purchase_id = %(purchase_id)s, assigned_cost_usd = 4.50, is_bulk = true
        where client_draft_id = %(draft)s
        """,
        {"purchase_id": compra["id"], "draft": draft},
    )
    fila = repository.obtener(clean_db, draft)
    assert fila.purchase_id == compra["id"]
    assert fila.assigned_cost_usd == Decimal("4.50")
    assert fila.is_bulk is True


# --- listar_fuera_del_151: el agujero negro de las cartas que no son de los 151 ---


def _sembrar_carta_sin_dex(conn, card_id="sv03.5-999", nombre="Profesor Oak"):
    """Una carta del catálogo cuyo `dexId` de TCGdex no trae número -- un
    entrenador, por ejemplo. `dex_number` queda null."""
    conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, raw)
        values (%s, %s, 'sv03.5', '151', %s, '{}'::jsonb)
        on conflict do nothing
        """,
        (card_id, nombre, card_id.rsplit("-", 1)[-1]),
    )


def _sembrar_carta_de_otra_generacion(conn, card_id="me02.5-008", nombre="Chikorita", dex=152):
    """Una carta real fuera del proyecto de los 151: Chikorita es dex 152."""
    conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, dex_number, image_url, raw)
        values (%s, %s, 'me02.5', 'Ascended Heroes', '008', %s, %s, '{}'::jsonb)
        on conflict do nothing
        """,
        (card_id, nombre, dex, f"https://x/{card_id}/high.png"),
    )


def test_listar_fuera_del_151_incluye_pokemon_de_otra_generacion(clean_db):
    from uuid import uuid4

    _sembrar_carta_de_otra_generacion(clean_db)
    clean_db.execute(
        "insert into app.owned_copy (client_draft_id, card_id) values (%s, 'me02.5-008')",
        (uuid4(),),
    )
    fuera = repository.listar_fuera_del_151(clean_db)
    assert len(fuera) == 1
    assert fuera[0]["card_name"] == "Chikorita"


def test_listar_fuera_del_151_incluye_carta_sin_dex_number(clean_db):
    from uuid import uuid4

    _sembrar_carta_sin_dex(clean_db)
    clean_db.execute(
        "insert into app.owned_copy (client_draft_id, card_id) values (%s, 'sv03.5-999')",
        (uuid4(),),
    )
    fuera = repository.listar_fuera_del_151(clean_db)
    assert len(fuera) == 1
    assert fuera[0]["card_name"] == "Profesor Oak"
    assert fuera[0]["dex_number"] is None


def test_listar_fuera_del_151_incluye_ejemplar_sin_carta_identificada(clean_db):
    from uuid import uuid4

    draft = uuid4()
    clean_db.execute("insert into app.owned_copy (client_draft_id) values (%s)", (draft,))
    fuera = repository.listar_fuera_del_151(clean_db)
    assert len(fuera) == 1
    assert fuera[0]["card_id"] is None
    assert fuera[0]["card_name"] is None


def test_listar_fuera_del_151_no_incluye_un_ejemplar_dentro_de_los_151(clean_db):
    from uuid import uuid4

    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    clean_db.execute(
        "insert into app.owned_copy (client_draft_id, card_id) values (%s, 'sv03.5-004')",
        (uuid4(),),
    )
    assert repository.listar_fuera_del_151(clean_db) == []


def test_listar_fuera_del_151_excluye_vendidas(clean_db):
    from uuid import uuid4

    _sembrar_carta_de_otra_generacion(clean_db)
    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, lifecycle_status)
        values (%s, 'me02.5-008', 'vendida')
        """,
        (uuid4(),),
    )
    assert repository.listar_fuera_del_151(clean_db) == []


def test_listar_fuera_del_151_trae_lo_necesario_para_dibujarla(clean_db):
    from uuid import uuid4

    _sembrar_carta_de_otra_generacion(clean_db)
    draft = uuid4()
    clean_db.execute(
        """
        insert into app.owned_copy
          (client_draft_id, card_id, variant_label, purchase_price_usd, photo_front_url, notes)
        values (%s, 'me02.5-008', 'holo', 3.00, %s, 'de un intercambio')
        """,
        (draft, f"{draft}/front.jpg"),
    )
    ejemplar = repository.listar_fuera_del_151(clean_db)[0]
    for campo in (
        "id",
        "card_id",
        "card_name",
        "set_name",
        "local_id",
        "dex_number",
        "image_url",
        "variant_label",
        "purchase_price_usd",
        "photo_front_url",
        "created_at",
    ):
        assert campo in ejemplar, f"falta {campo}"
    assert ejemplar["card_name"] == "Chikorita"
    assert ejemplar["dex_number"] == 152
    assert ejemplar["image_url"] == "https://x/me02.5-008/high.png"


def test_listar_fuera_del_151_muestra_el_costo_asignado_por_una_compra(clean_db):
    from uuid import uuid4

    _sembrar_carta_de_otra_generacion(clean_db)
    draft = uuid4()
    clean_db.execute(
        """
        insert into app.owned_copy
          (client_draft_id, card_id, purchase_price_usd, assigned_cost_usd)
        values (%s, 'me02.5-008', 3.00, 1.25)
        """,
        (draft,),
    )
    ejemplar = repository.listar_fuera_del_151(clean_db)[0]
    assert ejemplar["purchase_price_usd"] == Decimal("1.25")


def test_listar_fuera_del_151_sin_carta_no_trae_arte_del_catalogo(clean_db):
    """Un ejemplar sin `card_id` no tiene de dónde sacar el arte del
    catálogo: `image_url` viaja null, y la pantalla no tiene otra cosa que
    mostrar que la foto propia (si la hay)."""
    from uuid import uuid4

    clean_db.execute("insert into app.owned_copy (client_draft_id) values (%s)", (uuid4(),))
    ejemplar = repository.listar_fuera_del_151(clean_db)[0]
    assert ejemplar["image_url"] is None


def test_la_suma_de_las_dos_vistas_es_el_total_de_ejemplares(clean_db):
    """El test que impide que vuelva a existir el agujero negro: un ejemplar
    en cada una de las cinco situaciones posibles, y ninguno puede faltar ni
    contarse dos veces al sumar el binder ("dentro") y otras cartas
    ("fuera"). La quinta -- `dex_number` propio, sin `card_id` -- es la que
    agrega la task "identificar por lo impreso en la carta": el set puede
    quedar vacío si la especie ya se identificó bien."""
    from uuid import uuid4

    # dentro de los 151
    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    # otra generación: Chikorita, dex 152
    _sembrar_carta_de_otra_generacion(clean_db)
    # carta del catálogo sin dex_number (un entrenador)
    _sembrar_carta_sin_dex(clean_db)

    dentro = uuid4()
    otra_generacion = uuid4()
    sin_dex = uuid4()
    sin_carta = uuid4()
    dentro_por_dex_propio = uuid4()
    vendida = uuid4()
    id_dentro = clean_db.execute(
        "insert into app.owned_copy (client_draft_id, card_id) values (%s, 'sv03.5-004')"
        " returning id",
        (dentro,),
    ).fetchone()["id"]
    id_otra_generacion = clean_db.execute(
        "insert into app.owned_copy (client_draft_id, card_id) values (%s, 'me02.5-008')"
        " returning id",
        (otra_generacion,),
    ).fetchone()["id"]
    id_sin_dex = clean_db.execute(
        "insert into app.owned_copy (client_draft_id, card_id) values (%s, 'sv03.5-999')"
        " returning id",
        (sin_dex,),
    ).fetchone()["id"]
    id_sin_carta = clean_db.execute(
        "insert into app.owned_copy (client_draft_id) values (%s) returning id",
        (sin_carta,),
    ).fetchone()["id"]
    id_dentro_por_dex_propio = clean_db.execute(
        "insert into app.owned_copy (client_draft_id, dex_number) values (%s, 4) returning id",
        (dentro_por_dex_propio,),
    ).fetchone()["id"]
    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, lifecycle_status)
        values (%s, 'sv03.5-004', 'vendida')
        """,
        (vendida,),
    )

    total_no_vendidas = clean_db.execute(
        "select count(*) as n from app.owned_copy where lifecycle_status <> 'vendida'"
    ).fetchone()["n"]
    assert total_no_vendidas == 5, "sanity check del fixture"

    # El lado "dentro" es la consulta real del binder (`owned_count` de
    # `wishlist.repository.list_pokedex`, que camina las 151 filas de
    # `app.pokemon`) -- no `listar_por_dex` de un dex puntual, que no es la
    # vista que perdía al Chikorita.
    binder_total = sum(p["owned_count"] for p in wishlist_repository.list_pokedex(clean_db))
    fuera_del_151 = repository.listar_fuera_del_151(clean_db)

    assert binder_total == 2, "el de dex_number propio también cuelga de su casillero"
    # Identidades, no solo cantidades: dos fallas que se cancelan (un
    # ejemplar perdido y otro contado dos veces) sumarían igual y este test
    # tiene que detectarlo igual.
    assert {e["id"] for e in fuera_del_151} == {id_otra_generacion, id_sin_dex, id_sin_carta}
    assert id_dentro not in {e["id"] for e in fuera_del_151}
    assert id_dentro_por_dex_propio not in {e["id"] for e in fuera_del_151}
    assert binder_total + len(fuera_del_151) == total_no_vendidas, (
        "ningún ejemplar puede quedar en tierra de nadie ni contarse dos veces"
    )


# --- Task "identificar por lo impreso en la carta": owned_copy.dex_number ---


def test_un_ejemplar_sin_carta_pero_con_especie_cuelga_de_su_casillero(clean_db):
    """Lo que pidió el dueño: "permite que el set quede vacío, si es posible
    identificarlo bien, si no no pasa nada". Un ejemplar con `dex_number`
    propio (44, Gloom) y sin `card_id` cuenta en el casillero 44 y no
    aparece en "Otras cartas"."""
    from uuid import uuid4

    draft = uuid4()
    clean_db.execute(
        "insert into app.owned_copy (client_draft_id, dex_number) values (%s, 44)", (draft,)
    )

    ejemplares_del_casillero = repository.listar_por_dex(clean_db, 44)
    assert len(ejemplares_del_casillero) == 1
    assert ejemplares_del_casillero[0]["card_id"] is None

    assert repository.listar_fuera_del_151(clean_db) == []


def test_la_carta_manda_sobre_el_dex_number_propio_cuando_las_dos_existen(clean_db):
    """Si el ejemplar tiene `card_id` Y `dex_number` propio (ej. quedó de
    una inferencia anterior a resolverse la carta), el casillero de la
    carta es el que cuenta -- `coalesce(card.dex_number, owned_copy.
    dex_number)` prioriza la carta, no el respaldo."""
    from uuid import uuid4

    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    draft = uuid4()
    clean_db.execute(
        "insert into app.owned_copy (client_draft_id, card_id, dex_number) values (%s, %s, %s)",
        (draft, "sv03.5-004", 44),
    )

    assert len(repository.listar_por_dex(clean_db, 4)) == 1
    assert repository.listar_por_dex(clean_db, 44) == []
