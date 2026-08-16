import psycopg
import pytest


def test_las_tablas_de_wishlist_existen_en_app(db_conn):
    rows = db_conn.execute(
        "select tablename from pg_tables where schemaname = 'app' order by tablename"
    ).fetchall()
    nombres = [r["tablename"] for r in rows]
    assert "pokemon" in nombres
    assert "wishlist_item" in nombres


def test_rls_habilitada_en_las_tablas_nuevas(db_conn):
    rows = db_conn.execute(
        """
        select c.relname, c.relrowsecurity
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'app' and c.relkind = 'r'
        """
    ).fetchall()
    sin_rls = [r["relname"] for r in rows if not r["relrowsecurity"]]
    assert sin_rls == [], f"tablas de app sin RLS: {sin_rls}"


def test_la_misma_carta_se_puede_desear_en_dos_variantes(db_conn):
    """El caso de las 123 filas: normal y reverse de la misma carta."""
    db_conn.execute("insert into app.pokemon (dex_number, name) values (1, 'Bulbasaur')")
    db_conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, raw)
        values ('sv03.5-001', 'Bulbasaur', 'sv03.5', '151', '001', '{}'::jsonb)
        """
    )
    for variante, opcion in (("normal", "opcion_1"), ("reverse", "opcion_2")):
        db_conn.execute(
            """
            insert into app.wishlist_item
              (dex_number, card_id, variant_label, raw_text, source_option)
            values (1, 'sv03.5-001', %s, 'x', %s)
            """,
            (variante, opcion),
        )
    total = db_conn.execute(
        "select count(*) as n from app.wishlist_item where dex_number = 1"
    ).fetchone()["n"]
    assert total == 2


def test_no_se_puede_duplicar_la_misma_carta_y_variante(db_conn):
    db_conn.execute("insert into app.pokemon (dex_number, name) values (2, 'Ivysaur')")
    db_conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, raw)
        values ('sv03.5-002', 'Ivysaur', 'sv03.5', '151', '002', '{}'::jsonb)
        """
    )
    db_conn.execute(
        """
        insert into app.wishlist_item (dex_number, card_id, variant_label, raw_text, source_option)
        values (2, 'sv03.5-002', 'normal', 'x', 'opcion_1')
        """
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db_conn.execute(
            """
            insert into app.wishlist_item
              (dex_number, card_id, variant_label, raw_text, source_option)
            values (2, 'sv03.5-002', 'normal', 'otro texto', 'opcion_2')
            """
        )


def test_source_option_invalida_se_rechaza(db_conn):
    db_conn.execute("insert into app.pokemon (dex_number, name) values (3, 'Venusaur')")
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            """
            insert into app.wishlist_item (dex_number, raw_text, source_option)
            values (3, 'x', 'opcion_9')
            """
        )
