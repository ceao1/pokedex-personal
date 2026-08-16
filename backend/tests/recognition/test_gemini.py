import httpx
import pytest
import respx

from pokedex.recognition.gemini import GeminiRecognition, GeminiRequestError

MODEL = "gemini-3.5-flash"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def _gemini_response(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}


CHARIZARD_JSON = (
    '{"name":"Charizard","set_name":"Base Set","number":"4/102",'
    '"rarity":"Rare Holo","species":"Charizard","dex_number":6,'
    '"confidence":0.99,"needs_review":false}'
)


@respx.mock
async def test_una_respuesta_bien_formada_se_parsea():
    respx.post(URL).mock(return_value=httpx.Response(200, json=_gemini_response(CHARIZARD_JSON)))
    async with httpx.AsyncClient() as client:
        recognition = await GeminiRecognition("clave", MODEL, client).identify(
            b"foto", "image/jpeg"
        )

    assert recognition.name == "Charizard"
    assert recognition.set_name == "Base Set"
    assert recognition.number == "4/102"
    assert recognition.rarity == "Rare Holo"
    assert recognition.species == "Charizard"
    assert recognition.dex_number == 6
    assert recognition.confidence == 0.99
    assert recognition.needs_review is False


@respx.mock
async def test_json_envuelto_en_cerca_de_codigo_se_parsea_igual():
    texto = f"```json\n{CHARIZARD_JSON}\n```"
    respx.post(URL).mock(return_value=httpx.Response(200, json=_gemini_response(texto)))
    async with httpx.AsyncClient() as client:
        recognition = await GeminiRecognition("clave", MODEL, client).identify(
            b"foto", "image/jpeg"
        )

    assert recognition.name == "Charizard"
    assert recognition.number == "4/102"


@respx.mock
async def test_texto_que_no_es_json_no_lanza_excepcion():
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=_gemini_response("no puedo leer esta carta"))
    )
    async with httpx.AsyncClient() as client:
        recognition = await GeminiRecognition("clave", MODEL, client).identify(
            b"foto", "image/jpeg"
        )

    assert recognition.needs_review is True
    assert recognition.confidence == 0.0
    assert recognition.name is None


@respx.mock
async def test_un_429_se_propaga_como_error_sin_la_llave():
    respx.post(URL).mock(return_value=httpx.Response(429, json={"error": "rate limited"}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(GeminiRequestError) as excinfo:
            await GeminiRecognition("clave-secreta", MODEL, client).identify(b"foto", "image/jpeg")

    assert excinfo.value.status_code == 429
    assert "clave-secreta" not in str(excinfo.value)
    assert "clave-secreta" not in repr(excinfo.value)


@respx.mock
async def test_un_500_tambien_se_propaga():
    respx.post(URL).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as client:
        with pytest.raises(GeminiRequestError) as excinfo:
            await GeminiRecognition("clave", MODEL, client).identify(b"foto", "image/jpeg")
    assert excinfo.value.status_code == 500


@respx.mock
async def test_la_llave_viaja_en_query_string_no_en_authorization():
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json=_gemini_response(CHARIZARD_JSON))
    )
    async with httpx.AsyncClient() as client:
        await GeminiRecognition("clave-secreta", MODEL, client).identify(b"foto", "image/jpeg")

    request = route.calls.last.request
    assert request.url.params["key"] == "clave-secreta"
    assert "Authorization" not in request.headers
    assert "clave-secreta" not in request.headers.get("authorization", "")


@respx.mock
async def test_la_imagen_viaja_en_inline_data_con_su_mime_type():
    import base64
    import json

    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json=_gemini_response(CHARIZARD_JSON))
    )
    async with httpx.AsyncClient() as client:
        await GeminiRecognition("clave", MODEL, client).identify(b"bytes-de-foto", "image/png")

    body = json.loads(route.calls.last.request.content)
    inline_data = body["contents"][0]["parts"][1]["inline_data"]
    assert inline_data["mime_type"] == "image/png"
    assert base64.b64decode(inline_data["data"]) == b"bytes-de-foto"
