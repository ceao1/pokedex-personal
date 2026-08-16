import psycopg
import pytest


def test_las_tablas_del_catalogo_existen_en_el_esquema_app(db_conn):
    rows = db_conn.execute(
        "select tablename from pg_tables where schemaname = 'app' order by tablename"
    ).fetchall()
    nombres = [r["tablename"] for r in rows]
    assert "card" in nombres
    assert "card_variant" in nombres


def test_rls_habilitada_en_las_tablas_del_catalogo(db_conn):
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


def test_el_precio_y_su_fecha_van_juntos(db_conn):
    # Tras la CheckViolation la transacción queda abortada: no agregar
    # aserciones después del bloque `raises`, fallarían por eso y no por
    # lo que quieran verificar. El fixture hace rollback al terminar.
    db_conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, raw)
        values ('test-1', 'Test', 's', 'S', '1', '{}'::jsonb)
        """
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute(
            """
            insert into app.card_variant (id, card_id, type, price_usd, raw)
            values ('v1', 'test-1', 'normal', 1.00, '{}'::jsonb)
            """
        )
