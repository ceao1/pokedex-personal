"""Adaptador de `RecognitionPort` contra la API de Gemini (AI Studio).

Hechos verificados a mano contra la API real (ver el plan): la llave viaja
como `?key=`, no como `Authorization: Bearer` (eso da 401); `gemini-2.0-flash`
ya no existe (404); `gemini-3.5-flash` sí, y con `temperature: 0` +
`responseMimeType: application/json` responde en ~5s con el JSON pedido.
"""

import base64
import json
import re

import httpx
from pydantic import ValidationError

from .models import Recognition

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Los modelos envuelven el JSON en una cerca ```json ... ``` con cierta
# frecuencia aunque el prompt y `responseMimeType` pidan lo contrario.
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

_PROMPT = """Sos un identificador de cartas del Juego de Cartas Coleccionables \
Pokémon. Te doy la foto de una carta física y me devuelves SOLO un objeto \
JSON, sin texto adicional, con exactamente estas ocho claves:

- "name": el nombre impreso en la carta tal cual aparece (ej. "Charizard", \
"Erika's Gloom", "M Venusaur EX"). null si no se puede leer.
- "set_name": el nombre del set al que pertenece (ej. "Base Set"). null si \
no se puede determinar con certeza.
- "number": el número de colección impreso, en formato "N/total" (ej. \
"4/102"). Es el dato más importante: se usa para validar contra un \
catálogo real, así que es preferible admitir duda que inventar. Si no \
puedes leer el número con certeza -- por brillo, ángulo, o foto borrosa --
devuelve null, baja "confidence" y marca "needs_review": true. Un número \
inventado que casualmente exista en el catálogo es el peor resultado \
posible, porque pasaría la validación sin que nadie note el error.
- "rarity": la rareza impresa (ej. "Rare Holo"). null si no aplica o no se \
puede leer.
- "species": el Pokémon base de la carta, SIN el nombre del entrenador ni \
sufijos de carta -- distinto de "name". Por ejemplo, para "Erika's Gloom" \
species es "Gloom"; para "Charizard ex" es "Charizard"; para "M Venusaur \
EX" es "Venusaur". null si la carta es un Entrenador o una Energía (no es \
un Pokémon).
- "dex_number": el número de Pokédex nacional de esa especie, como entero \
(ej. Charizard es 6). null si la carta no es un Pokémon, o si no estás \
seguro de la especie.
- "confidence": un número entre 0 y 1 que refleje qué tan seguro estás de \
la lectura completa, no solo del nombre.
- "needs_review": true si hay cualquier duda real sobre el número, el set \
o la especie -- ante la duda, preferí true. false solo si leíste la carta \
con certeza.

Devuelve únicamente el objeto JSON, sin explicación ni formato adicional."""


class GeminiRecognition:
    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client

    async def identify(self, image: bytes, mime_type: str) -> Recognition:
        url = _ENDPOINT.format(model=self._model)
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": _PROMPT},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64.b64encode(image).decode("ascii"),
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        try:
            response = await self._client.post(url, params={"key": self._api_key}, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # `str(exc)`/`repr(exc)` de httpx incluyen la URL completa de la
            # petición -- que acá trae `?key=...` en la query string. Se
            # relanza una excepción propia con solo el status, nunca la
            # excepción original, para que la llave no pueda llegar a un log
            # ni a una respuesta HTTP por esta vía. Sigue siendo un error
            # real (se propaga, no se disfraza de "no reconocida"): un 429 o
            # un 5xx es "no pude preguntar", distinto de "no sé qué carta
            # es", y el primero merece reintento -- el segundo, revisión.
            raise GeminiRequestError(exc.response.status_code) from None
        text = _extract_text(response.json())
        return _parse(text)


class GeminiRequestError(Exception):
    """La API de Gemini respondió con un error (429, 5xx, etc.).

    No lleva el mensaje de httpx a propósito: ese mensaje incluye la URL de
    la petición con la llave en la query string, y esta excepción puede
    terminar en un log o, sin cuidado, en una respuesta HTTP.
    """

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Gemini respondió {status_code}")


def _extract_text(body: dict) -> str:
    return body["candidates"][0]["content"]["parts"][0]["text"]


def _parse(text: str) -> Recognition:
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        # Texto que no es JSON -- una carta mal leída no puede tumbar el
        # registro, así que esto es un resultado normal, no una excepción.
        return Recognition(needs_review=True, confidence=0.0, raw={"text": text})
    if not isinstance(data, dict):
        return Recognition(needs_review=True, confidence=0.0, raw={"text": text})
    try:
        return Recognition(
            name=data.get("name"),
            set_name=data.get("set_name"),
            number=data.get("number"),
            rarity=data.get("rarity"),
            species=data.get("species"),
            dex_number=data.get("dex_number"),
            confidence=float(data.get("confidence") or 0.0),
            needs_review=bool(data.get("needs_review", True)),
            raw=data,
        )
    except (ValidationError, TypeError, ValueError):
        # El JSON parseó pero algún campo vino con un tipo inesperable (ej.
        # `dex_number: "seis"`). Mismo principio que un JSON inválido: una
        # lectura rara no puede tumbar el registro.
        return Recognition(needs_review=True, confidence=0.0, raw=data)


class FakeRecognition:
    """Doble de `RecognitionPort` para tests: no pega a la red."""

    def __init__(self, result: Recognition | None = None, error: Exception | None = None) -> None:
        self.result = result if result is not None else Recognition()
        self.error = error
        self.calls: list[tuple[bytes, str]] = []

    async def identify(self, image: bytes, mime_type: str) -> Recognition:
        self.calls.append((image, mime_type))
        if self.error is not None:
            raise self.error
        return self.result
