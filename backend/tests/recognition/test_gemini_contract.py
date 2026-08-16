"""Verifica que Gemini sigue devolviendo la forma que asumimos.

Excluido de la suite por defecto (marca `contract`, la misma que usan los
tests de contrato de TCGdex). Correr a mano:
    uv run pytest -m contract -v

Un solo test, una sola llamada: cada corrida cuesta dinero real del dueño.
Si `GEMINI_API` no está configurada (ej. en CI), se salta en vez de fallar.
"""

import httpx
import pytest

from pokedex.config import settings
from pokedex.recognition.gemini import GeminiRecognition

pytestmark = pytest.mark.contract

CARD_IMAGE_URL = "https://assets.tcgdex.net/en/base/base1/4/high.png"


async def test_identifica_charizard_de_base_set_por_su_arte():
    if not settings.gemini_api:
        pytest.skip("GEMINI_API no configurada")

    async with httpx.AsyncClient(timeout=30) as client:
        image = (await client.get(CARD_IMAGE_URL)).content
        recognition = await GeminiRecognition(
            settings.gemini_api, settings.gemini_model, client
        ).identify(image, "image/png")

    assert recognition.name is not None and "charizard" in recognition.name.casefold()
    assert recognition.number is not None and "4/102" in recognition.number
