"""El adaptador de Storage: qué URL recibe el navegador.

Estos tests no pegan a la red. Verifican la construcción de URLs, que es
donde estuvo el fallo: el backend firmaba con su propia base de loopback y
se la entregaba al celular, para el cual `127.0.0.1` es el propio celular.
La subida se rechazaba y la foto se perdía en silencio, porque el flujo
está diseñado para poder guardar sin ella.
"""

import httpx
import pytest
import respx

from pokedex.collection.storage import AlreadyUploaded, SupabaseStorage

INTERNA = "http://127.0.0.1:54321"
PUBLICA = "http://192.168.1.50:54321"
BUCKET = "card-photos"
RUTA = "abc/front.jpg"

_FIRMA_OK = {"url": f"object/upload/sign/{BUCKET}/{RUTA}?token=eyJfake"}


def _mock_firma_subida():
    return respx.post(f"{INTERNA}/storage/v1/object/upload/sign/{BUCKET}/{RUTA}").mock(
        return_value=httpx.Response(200, json=_FIRMA_OK)
    )


@respx.mock
async def test_la_url_entregada_al_cliente_usa_la_base_publica():
    """El caso que rompía la app entera en el celular."""
    _mock_firma_subida()
    async with httpx.AsyncClient() as client:
        storage = SupabaseStorage(INTERNA, "secreto", BUCKET, client, public_base_url=PUBLICA)
        firmada = await storage.create_signed_upload(RUTA)

    assert firmada.signed_url.startswith(PUBLICA), firmada.signed_url
    assert "127.0.0.1" not in firmada.signed_url
    assert "localhost" not in firmada.signed_url


@respx.mock
async def test_el_servidor_sigue_firmando_contra_su_base_interna():
    """La base pública es solo para el cliente: el backend habla por loopback."""
    ruta_interna = _mock_firma_subida()
    async with httpx.AsyncClient() as client:
        storage = SupabaseStorage(INTERNA, "secreto", BUCKET, client, public_base_url=PUBLICA)
        await storage.create_signed_upload(RUTA)

    assert ruta_interna.called, "la petición de firma no salió por la base interna"


@respx.mock
async def test_sin_base_publica_se_usa_la_interna():
    """Escritorio: abrir en localhost no necesita configuración extra."""
    _mock_firma_subida()
    async with httpx.AsyncClient() as client:
        storage = SupabaseStorage(INTERNA, "secreto", BUCKET, client)
        firmada = await storage.create_signed_upload(RUTA)

    assert firmada.signed_url.startswith(INTERNA)


@respx.mock
async def test_la_descarga_firmada_tambien_usa_la_base_publica():
    """De nada sirve subir la foto si el celular no puede mostrarla."""
    respx.post(f"{INTERNA}/storage/v1/object/sign/{BUCKET}/{RUTA}").mock(
        return_value=httpx.Response(200, json={"signedURL": f"object/sign/{BUCKET}/{RUTA}?token=x"})
    )
    async with httpx.AsyncClient() as client:
        storage = SupabaseStorage(INTERNA, "secreto", BUCKET, client, public_base_url=PUBLICA)
        url = await storage.signed_download_url(RUTA)

    assert url.startswith(PUBLICA)
    assert "127.0.0.1" not in url


@respx.mock
async def test_un_objeto_ya_subido_se_distingue_de_un_error():
    respx.post(f"{INTERNA}/storage/v1/object/upload/sign/{BUCKET}/{RUTA}").mock(
        return_value=httpx.Response(400, json={"statusCode": "409", "error": "Duplicate"})
    )
    async with httpx.AsyncClient() as client:
        storage = SupabaseStorage(INTERNA, "secreto", BUCKET, client, public_base_url=PUBLICA)
        with pytest.raises(AlreadyUploaded):
            await storage.create_signed_upload(RUTA)


@respx.mock
async def test_un_error_real_sigue_propagando():
    """No tragarse todos los errores para tapar el caso del duplicado."""
    respx.post(f"{INTERNA}/storage/v1/object/upload/sign/{BUCKET}/{RUTA}").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )
    async with httpx.AsyncClient() as client:
        storage = SupabaseStorage(INTERNA, "secreto", BUCKET, client, public_base_url=PUBLICA)
        with pytest.raises(httpx.HTTPStatusError):
            await storage.create_signed_upload(RUTA)
