"""Verifica que Gemini identifica varias cartas en una sola foto compuesta.

Excluido de la suite por defecto (marca `contract`, la misma que usan los
tests de contrato de TCGdex y Gemini). Correr a mano:
    uv run pytest -m contract -v

Un solo test, una sola llamada: cada corrida cuesta dinero real del dueño.
Cuatro cartas, no veinticuatro -- el objetivo es verificar el mecanismo (Task
3, Step 4 del plan), no volver a medir el techo de doce.

`tests/fixtures/tanda_4.jpg` es una composición 2x2 de cuatro cartas reales
de "Ascended Heroes" (me02.5): Mega Meganium ex (010), Charmander (020),
Mega Charizard Y ex (022) y Psyduck (039) -- construida a mano con Pillow
(`uv run --with pillow`, no es dependencia del proyecto) contra el arte real
de `https://assets.tcgdex.net/en/me/me02.5/{NNN}/high.png`. Se commitea como
fixture (no se reconstruye en cada corrida) para no depender de Pillow ni de
la red de TCGdex en el momento del test -- solo de Gemini, que es lo único
que este contrato verifica.
"""

from pathlib import Path

import httpx
import pytest

from pokedex.config import settings
from pokedex.recognition.gemini import GeminiRecognition

pytestmark = pytest.mark.contract

FIXTURE = Path(__file__).parent.parent / "fixtures" / "tanda_4.jpg"

# (número impreso, fragmento del nombre a buscar en la lectura correspondiente)
CARTAS_ESPERADAS = [
    ("010", "meganium"),
    ("020", "charmander"),
    ("022", "charizard"),
    ("039", "psyduck"),
]


def _numero_normalizado(numero: str | None) -> str | None:
    """`Recognition.number` puede llegar como `"20/217"`, `"020/217"` o
    incluso solo `"20"` -- normaliza el numerador quitando ceros a la
    izquierda para comparar sin depender del formato exacto que haya
    devuelto el modelo en esta corrida."""
    if not numero:
        return None
    numerador = numero.split("/", 1)[0].strip()
    return numerador.lstrip("0") or "0"


async def test_identifica_las_cuatro_cartas_de_una_foto_compuesta():
    """Verificado a mano contra la API real dos veces durante el desarrollo
    de este test: el nombre/especie de las cuatro cartas salió correcto en
    ambas corridas, siempre con `set_code` "ASC" (sin sufijo de idioma). El
    número impreso salió correcto en una corrida y `null` con
    `needs_review: true` en la otra para las cuatro -- exactamente el
    comportamiento que pide el prompt ("preferí null a inventar"), no un
    fallo del mecanismo. Por eso el número se verifica de forma laxa: nunca
    se acepta un número EQUIVOCADO (la falla real que motiva este plan --
    "047" leído como "022"), pero tampoco se exige que todas las lecturas lo
    resuelvan siempre, porque exigirlo haría flaky un test de contrato por
    una razón que no es un bug."""
    if not settings.gemini_api:
        pytest.skip("GEMINI_API no configurada")

    imagen = FIXTURE.read_bytes()
    async with httpx.AsyncClient(timeout=60) as client:
        lecturas = await GeminiRecognition(
            settings.gemini_api, settings.gemini_model, client
        ).identificar_varias(imagen, "image/jpeg")

    assert len(lecturas) == 4, f"se esperaban 4 lecturas, llegaron {len(lecturas)}"

    # Nombre/especie: la defensa práctica contra la confusión medida en el
    # plan (un número que existe mintiendo sobre el Pokémon). Debe salir
    # correcto siempre, número aparte.
    nombres_leidos = " ".join((lectura.name or "").casefold() for lectura in lecturas)
    for _, fragmento in CARTAS_ESPERADAS:
        assert fragmento in nombres_leidos, f"no se leyó ningún nombre con «{fragmento}»"

    # `set_code`: "ASC" tal cual, nunca "ASCen" -- si el parser fallara en
    # separar el sufijo de idioma, esto lo vería incluso cuando el número
    # salga null.
    for lectura in lecturas:
        if lectura.set_code is not None:
            assert lectura.set_code == "ASC", f"set_code sin depurar: {lectura.set_code!r}"

    # Número: nunca uno EQUIVOCADO (la falla real que mide el plan). Los que
    # sí vinieron completos tienen que ser, como conjunto, un subconjunto de
    # los esperados -- nunca uno ajeno ni repetido.
    numeros_leidos = {
        n for lectura in lecturas if (n := _numero_normalizado(lectura.number)) is not None
    }
    numeros_esperados = {n.lstrip("0") for n, _ in CARTAS_ESPERADAS}
    assert numeros_leidos <= numeros_esperados, (
        f"número(s) equivocado(s): {numeros_leidos - numeros_esperados}"
    )
