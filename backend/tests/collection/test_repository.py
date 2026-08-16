from uuid import UUID

from pokedex.collection import repository
from pokedex.collection.models import OwnedCopyIn


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
