import psycopg
import pytest


def _sembrar_carta_con_variante(conn, card_id="sv03.5-001", variant_id="v-normal"):
    # local_id se deriva de card_id (no se hardcodea '001'): app.card tiene un
    # índice único en (set_id, local_id), y con un local_id fijo la segunda
    # carta sembrada choca en silencio contra `on conflict do nothing`, deja
    # de existir, y el test deja de probar lo que dice probar.
    local_id = card_id.rsplit("-", 1)[-1]
    conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, raw)
        values (%s, 'Bulbasaur', 'sv03.5', '151', %s, '{}'::jsonb)
        on conflict do nothing
        """,
        (card_id, local_id),
    )
    conn.execute(
        """
        insert into app.card_variant (id, card_id, type, raw)
        values (%s, %s, 'normal', '{}'::jsonb)
        on conflict do nothing
        """,
        (variant_id, card_id),
    )


def test_las_tablas_de_coleccion_existen_con_rls(db_conn):
    rows = db_conn.execute(
        """
        select c.relname, c.relrowsecurity
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'app' and c.relkind = 'r'
        """
    ).fetchall()
    por_nombre = {r["relname"]: r["relrowsecurity"] for r in rows}
    assert "owned_copy" in por_nombre
    assert "binder" in por_nombre
    sin_rls = [n for n, rls in por_nombre.items() if not rls]
    assert sin_rls == [], f"tablas de app sin RLS: {sin_rls}"


def test_un_ejemplar_minimo_se_guarda(clean_db):
    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id)
        values ('11111111-1111-1111-1111-111111111111')
        """
    )
    fila = clean_db.execute(
        "select capture_status, lifecycle_status, graded from app.owned_copy"
    ).fetchone()
    assert fila["capture_status"] == "borrador"
    assert fila["lifecycle_status"] == "en_binder"
    assert fila["graded"] is False


def test_el_client_draft_id_es_unico(clean_db):
    for _ in range(2):
        try:
            clean_db.execute(
                """
                insert into app.owned_copy (client_draft_id)
                values ('22222222-2222-2222-2222-222222222222')
                """
            )
        except psycopg.errors.UniqueViolation:
            return
    raise AssertionError("se permitió duplicar client_draft_id")


def test_no_se_puede_asignar_una_variante_de_otra_carta(clean_db):
    """La foránea compuesta es lo que impide guardar un Bulbasaur con la
    variante de un Charizard."""
    _sembrar_carta_con_variante(clean_db, "sv03.5-001", "v-a")
    _sembrar_carta_con_variante(clean_db, "sv03.5-002", "v-b")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        clean_db.execute(
            """
            insert into app.owned_copy (client_draft_id, card_id, variant_id)
            values ('33333333-3333-3333-3333-333333333333', 'sv03.5-001', 'v-b')
            """
        )


def test_variant_id_sin_card_id_se_rechaza(clean_db):
    """La FK compuesta usa MATCH SIMPLE (el default de Postgres): se salta la
    validación por completo si cualquiera de las dos columnas es null.
    card_id es null en todo borrador que aún no identificó su carta -- el
    estado normal de un ejemplar en captura -- así que sin este check un
    variant_id suelto pasaba sin que la base lo rechazara."""
    with pytest.raises(psycopg.errors.CheckViolation):
        clean_db.execute(
            """
            insert into app.owned_copy (client_draft_id, variant_id)
            values ('66666666-6666-6666-6666-666666666666', 'inventado-no-existe')
            """
        )


def test_card_id_sin_variant_id_se_acepta(clean_db):
    """El check no debe bloquear este caso: el dueño identificó la carta
    pero todavía no eligió el print/variante -- estado legítimo, y del que
    depende `owned_count` (ver tests/wishlist/test_repository.py), que
    cuenta ejemplares por `card_id` sin exigir `variant_id`."""
    _sembrar_carta_con_variante(clean_db, "sv03.5-004", "v-d")
    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id)
        values ('88888888-8888-8888-8888-888888888888', 'sv03.5-004')
        """
    )
    fila = clean_db.execute(
        "select variant_id from app.owned_copy where card_id = 'sv03.5-004'"
    ).fetchone()
    assert fila["variant_id"] is None


def test_variante_completa_se_acepta(clean_db):
    """El check no estorba el caso normal: card_id y variant_id juntos, de
    una variante que sí existe para esa carta."""
    _sembrar_carta_con_variante(clean_db, "sv03.5-003", "v-c")
    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, variant_id)
        values ('77777777-7777-7777-7777-777777777777', 'sv03.5-003', 'v-c')
        """
    )
    fila = clean_db.execute(
        """
        select card_id, variant_id from app.owned_copy
        where client_draft_id = '77777777-7777-7777-7777-777777777777'
        """
    ).fetchone()
    assert fila["card_id"] == "sv03.5-003"
    assert fila["variant_id"] == "v-c"


def test_gradeada_sin_empresa_se_rechaza(clean_db):
    with pytest.raises(psycopg.errors.CheckViolation):
        clean_db.execute(
            """
            insert into app.owned_copy (client_draft_id, graded)
            values ('44444444-4444-4444-4444-444444444444', true)
            """
        )


def test_un_capture_status_invalido_se_rechaza(clean_db):
    with pytest.raises(psycopg.errors.CheckViolation):
        clean_db.execute(
            """
            insert into app.owned_copy (client_draft_id, capture_status)
            values ('55555555-5555-5555-5555-555555555555', 'inventado')
            """
        )
