"""Verifica que `GeminiRecognition.elegir_entre` distingue entre dos cartas
reales del mismo Pokémon en sets distintos.

Excluido de la suite por defecto (marca `contract`, la misma que usan los
tests de contrato de TCGdex y Gemini). Correr a mano:
    uv run pytest -m contract -v

Un solo test, una sola llamada: cada corrida cuesta dinero real del dueño.
Si `GEMINI_API` no está configurada (ej. en CI), se salta en vez de fallar.
"""

import httpx
import pytest

from pokedex.config import settings
from pokedex.recognition.gemini import GeminiRecognition
from pokedex.recognition.ports import CandidataImagen

pytestmark = pytest.mark.contract

# Dos Bulbasaur reales, arte completamente distinto: Base Set (1999) y "151"
# (sv03.5, 2023) -- verificado a mano contra la API real de TCGdex.
BASE_SET_BULBASAUR = "https://assets.tcgdex.net/en/base/base1/44/high.png"
SET_151_BULBASAUR = "https://assets.tcgdex.net/en/sv/sv03.5/001/high.png"


async def test_elige_la_candidata_correcta_entre_dos_bulbasaur_reales():
    if not settings.gemini_api:
        pytest.skip("GEMINI_API no configurada")

    async with httpx.AsyncClient(timeout=30) as client:
        # La "foto del dueño" es, para este contrato, el arte oficial de la
        # carta de sv03.5 -- no hace falta una foto casera para verificar
        # que el modelo distingue entre dos artes reales y elige la que
        # coincide.
        foto = (await client.get(SET_151_BULBASAUR)).content
        arte_base = (await client.get(BASE_SET_BULBASAUR)).content

        elegido = await GeminiRecognition(
            settings.gemini_api, settings.gemini_model, client
        ).elegir_entre(
            foto,
            [
                CandidataImagen(card_id="base1-44", image=arte_base),
                CandidataImagen(card_id="sv03.5-001", image=foto),
            ],
        )

    assert elegido == "sv03.5-001"
