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
