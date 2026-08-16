import httpx

from pokedex.catalog.errors import CATALOG_NETWORK_ERRORS, es_error_de_servidor


def test_los_errores_de_red_cubren_timeout_y_conexion():
    assert CATALOG_NETWORK_ERRORS == (
        httpx.ConnectTimeout,
        httpx.ConnectError,
        httpx.ReadTimeout,
    )


def test_un_5xx_es_error_de_servidor():
    request = httpx.Request("GET", "https://x/cards/1")
    response = httpx.Response(502, request=request)
    exc = httpx.HTTPStatusError("502", request=request, response=response)
    assert es_error_de_servidor(exc) is True


def test_un_4xx_no_es_error_de_servidor():
    request = httpx.Request("GET", "https://x/cards/1")
    response = httpx.Response(404, request=request)
    exc = httpx.HTTPStatusError("404", request=request, response=response)
    assert es_error_de_servidor(exc) is False
