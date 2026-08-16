"""Valida la respuesta del modelo de reconocimiento contra el catálogo real.

Acá es donde el reconocimiento se gana el derecho a ser creído (spec §5.2,
task "identificar por lo impreso en la carta"): se apoya en lo que está
*impreso junto al número* -- el código del set y el número `NNN/TTT` -- en
vez de en el nombre del set, que el modelo tiene que recordar en vez de leer.

La cascada, en orden, parando en cuanto un paso produce un resultado:

1. **Código de set** (`set_code` contra `abbreviation.official`). Único
   entre 188 de los 218 sets del catálogo (verificado): la señal más
   fuerte. Si el código no existe en el catálogo, se cae al paso 2. Si
   existe, es autoritativo: dio un solo set, y ese set decide la
   resolución (o el rechazo) sin mirar más allá.
2. **Denominador** (`TTT` contra `cardCount.official`). Puede dar varios
   sets -- hay tamaños repetidos -- así que cada uno se prueba y se
   quedan los que confirman.
3. **`set_name`**, si el modelo lo dio y resuelve a un set conocido.
4. Sin resolver, con motivo explícito.

Una candidata (carta real en `(set, número)`) se acepta si **al menos una**
señal coincide sin que **ninguna** contradiga: el `dexId` de la carta
contra el `dex_number` leído, o el nombre de la carta contra el nombre
leído o la especie. Una contradicción explícita (el `dexId` es 25 y el
modelo leyó 44) rechaza aunque otra señal luzca parecida.

`needs_review` y la confianza del modelo ya **no vetan**: se conservan en
la respuesta para que la pantalla las muestre, pero lo único que impide
proponer una carta es la falta de confirmación del catálogo. Cuando el
modelo dudaba y el catálogo confirma, el motivo lo dice.

Cuando el catálogo deja más de una candidata confirmada (mismo número,
mismo denominador, ninguna se distingue por nombre/dexId), no se elige
ninguna: quedan en `ResolucionCarta.candidatas` para revisión manual --
nunca una adivinanza (ver `_resolver_en_sets`).

También intenta rellenar `Card.dex_number` cuando falta (cartas de
entrenador tipo "Erika's Gloom", que TCGdex no etiqueta con `dexId`) usando
`species`/`dex_number` del reconocimiento -- pero solo si esa inferencia
coincide con `app.pokemon`, la fuente autoritativa de los 151. Si las dos
señales se contradicen, no se adivina cuál vale: revisión manual.
"""

import re
import unicodedata

from pydantic import BaseModel

from pokedex.catalog import repository as catalog_repository
from pokedex.catalog.models import Card
from pokedex.catalog.service import CatalogService

from .models import Recognition

# Piloteado, no medido: punto de partida para decidir cuándo el motivo de
# éxito debe mencionar que el modelo dudó (ver `_motivo_exito`). Ya no es un
# veto -- la evidencia que motivó esta task (dos cartas reales, una con
# confidence 0.5) mostró que vetar por esto tiraba lecturas que el catálogo
# confirmaba en tres vías independientes.
CONFIDENCE_THRESHOLD = 0.7

# Rango de la Pokédex que cubre este proyecto (spec: "los 151 originales").
# Un dex_number fuera de este rango no es un error del modelo -- es una
# carta fuera de alcance -- así que no se infiere ni se marca revisión.
DEX_MIN, DEX_MAX = 1, 151

_NUMBER_WITH_SLASH_RE = re.compile(r"^\s*([^\s/]+)\s*/\s*(\d+)\s*$")
_NUMBER_BARE_RE = re.compile(r"^\s*([^\s/]+)\s*$")

# Sufijos de carta que no forman parte del nombre de la especie/Pokémon.
# Se despojan de ambos lados antes de comparar -- así "Charizard" (lo que
# dijo el modelo) coincide con "Charizard ex" (el nombre de la carta) sin
# hacer coincidencia parcial agresiva sobre el resto del nombre.
_SUFFIX_RE = re.compile(r"\s+(ex|gx|v|vmax|vstar|vunion|prime|break|lv\.x)$", re.IGNORECASE)

# Posesivo de entrenador al inicio del nombre de una carta ("Erika's Gloom")
# -- se despoja antes de comparar contra `species`, que nunca lo lleva
# ("Gloom"). Solo la primera ocurrencia: un nombre no debería traer más de
# un posesivo, pero de haberlo, el resto se conserva tal cual.
_POSSESSIVE_RE = re.compile(r"^[^'\s]+'s\s+", re.IGNORECASE)

_SELECT_POKEMON_NAME = "select name from app.pokemon where dex_number = %(dex_number)s"


class ResolucionCarta(BaseModel):
    card: Card | None = None
    motivo: str
    necesita_revision: bool = False
    # Cuando el catálogo confirma más de una carta para el mismo (set,
    # número) -- ver `_resolver_en_sets` -- y no hubo cómo desempatar (sin
    # foto, sin `RecognitionPort`, o el desempate no distinguió), quedan acá
    # para que la pantalla pueda mostrarlas u ofrecer un desempate manual.
    # Vacía en cualquier otro caso, incluido el éxito con una sola carta.
    candidatas: list[Card] = []


def _normalize_name(name: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    resultado = sin_acentos.strip().casefold()
    resultado = _POSSESSIVE_RE.sub("", resultado)
    # Repetido: un nombre podría traer más de un sufijo pegado (no debería,
    # pero es gratis cubrirlo) y cada pasada solo saca uno.
    anterior = None
    while anterior != resultado:
        anterior = resultado
        resultado = _SUFFIX_RE.sub("", resultado).strip()
    return resultado


def _normalize_number_part(value: str) -> str:
    return value.strip().casefold().lstrip("0") or "0"


def _parse_number(number: str) -> tuple[str, str | None] | None:
    match = _NUMBER_WITH_SLASH_RE.match(number)
    if match is not None:
        return match.group(1), match.group(2)
    match = _NUMBER_BARE_RE.match(number)
    if match is not None:
        return match.group(1), None
    return None


def _confirmar(reconocido: Recognition, card: Card) -> tuple[bool | None, str]:
    """Evalúa una candidata contra las señales del reconocimiento.

    Devuelve `(True, "")` si al menos una señal confirma sin que otra
    contradiga; `(False, motivo)` si hay una contradicción explícita
    (rechazo, sin importar que otra señal luzca parecida); `(None, "")` si
    no hay señal suficiente ni para confirmar ni para contradecir (la carta
    existe en `(set, número)` pero eso solo, sin nombre ni dexId que lo
    respalden, no basta -- ver el docstring del módulo).

    `nombre` y `especie` cuentan como **una sola** señal combinada (el
    plan las une con "o": "el nombre coincide con el nombre leído o con la
    especie"), no dos independientes: si `name` calza exacto con la carta,
    una `species` mal leída o ajena (ej. un dato de relleno del modelo) no
    puede tumbar esa confirmación por su cuenta. Lo que sí sigue siendo un
    veto absoluto es el `dexId`: es un dato numérico del catálogo, no una
    lectura de texto con la que el modelo pueda "acercarse".
    """
    señales: list[tuple[str, bool]] = []

    if card.dex_number is not None and reconocido.dex_number is not None:
        señales.append(("dex", card.dex_number == reconocido.dex_number))

    nombre_carta = _normalize_name(card.name)
    lecturas_de_nombre = [t for t in (reconocido.name, reconocido.species) if t]
    if lecturas_de_nombre:
        señales.append(
            ("nombre", any(_normalize_name(t) == nombre_carta for t in lecturas_de_nombre))
        )

    if any(ok is False for _, ok in señales):
        detalle = ", ".join(tipo for tipo, ok in señales if ok is False)
        return False, (
            f"la carta encontrada en el catálogo es «{card.name}» ({card.set_name} "
            f"{card.local_id}), pero no coincide con lo leído ({detalle}): "
            "señales contradictorias"
        )
    if any(ok is True for _, ok in señales):
        return True, ""
    return None, ""


class CardResolver:
    def __init__(self, catalog: CatalogService, conn_factory) -> None:
        self._catalog = catalog
        self._conn_factory = conn_factory

    async def resolver(self, reconocido: Recognition) -> ResolucionCarta:
        if not reconocido.number:
            return ResolucionCarta(
                motivo="el modelo no devolvió el número de colección", necesita_revision=True
            )
        parsed = _parse_number(reconocido.number)
        if parsed is None:
            return ResolucionCarta(
                motivo=f"el número «{reconocido.number}» no tiene un formato reconocible",
                necesita_revision=True,
            )
        numerator, denominator_str = parsed
        denominator = int(denominator_str) if denominator_str is not None else None

        # Paso 1: código de set -- la señal más fuerte, única cuando existe.
        if reconocido.set_code:
            set_por_codigo = await self._catalog.set_por_codigo(reconocido.set_code)
            if set_por_codigo is not None:
                if (
                    denominator is not None
                    and set_por_codigo.total is not None
                    and denominator != set_por_codigo.total
                ):
                    return ResolucionCarta(
                        motivo=(
                            f"el código «{reconocido.set_code}» corresponde a "
                            f"{set_por_codigo.name} ({set_por_codigo.total} cartas), pero el "
                            f"número dice {denominator}: señales contradictorias"
                        ),
                        necesita_revision=True,
                    )
                resultado = await self._resolver_en_sets([set_por_codigo], numerator, reconocido)
                if resultado is not None:
                    return resultado
                # El código es autoritativo: dio un único set real. Si la
                # carta no existe ahí, no se cae al denominador -- sería
                # abandonar la señal más fuerte por una más débil sin
                # ningún motivo real para desconfiar de ella.
                return ResolucionCarta(
                    motivo=(
                        f"el código «{reconocido.set_code}» señala {set_por_codigo.name}, pero "
                        f"no existe la carta {numerator} ahí"
                    ),
                    necesita_revision=True,
                )
            # El código no existe en el catálogo -- cae al denominador.

        # Paso 2: denominador -- puede dar varios sets; se prueban todos.
        if denominator is not None:
            sets_por_total = await self._catalog.sets_por_total(denominator)
            if sets_por_total:
                resultado = await self._resolver_en_sets(sets_por_total, numerator, reconocido)
                if resultado is not None:
                    return resultado

        # Paso 3: set_name, si el modelo lo dio y resuelve a un set conocido.
        if reconocido.set_name:
            set_por_nombre = await self._buscar_set(reconocido.set_name)
            if set_por_nombre is not None:
                resultado = await self._resolver_en_sets([set_por_nombre], numerator, reconocido)
                if resultado is not None:
                    return resultado

        # Paso 4: sin resolver.
        return ResolucionCarta(
            motivo=(
                "no se pudo identificar el set: sin código de set válido, sin denominador que "
                "resuelva contra el catálogo, y sin nombre de set reconocible"
            ),
            necesita_revision=True,
        )

    async def _resolver_en_sets(
        self, sets, numerator: str, reconocido: Recognition
    ) -> ResolucionCarta | None:
        """Busca la carta `numerator` en cada set y aplica `_confirmar`.

        Devuelve `None` -- "nada encontrado, seguir con el próximo paso de
        la cascada" -- solo cuando ningún set de la lista tiene esa carta en
        absoluto. Un rechazo por contradicción, o un éxito (uno o varios
        confirmados), siempre devuelve una `ResolucionCarta`: son
        resultados, no ausencia de ellos.
        """
        objetivo = _normalize_number_part(numerator)
        confirmados: list[Card] = []
        contradicciones: list[tuple[Card, str]] = []

        for set_ref in sets:
            cartas = await self._catalog.list_set_cards(set_ref.id)
            coincidencia = next(
                (c for c in cartas if _normalize_number_part(c.local_id) == objetivo), None
            )
            if coincidencia is None:
                continue
            card = await self._catalog.get_card(coincidencia.id)
            if card is None:
                continue
            confirma, motivo = _confirmar(reconocido, card)
            if confirma is True:
                confirmados.append(card)
            elif confirma is False:
                contradicciones.append((card, motivo))

        if len(confirmados) == 1:
            return await self._finalizar(confirmados[0], reconocido)

        if confirmados:
            # Más de una candidata confirmada y ninguna se distingue por
            # nombre/dexId: no se elige al azar.
            return ResolucionCarta(
                motivo=(
                    f"el número calzaba con {len(confirmados)} cartas del catálogo sin que "
                    "ninguna señal las distinga: hace falta revisión manual"
                ),
                necesita_revision=True,
                candidatas=confirmados,
            )

        if contradicciones:
            return ResolucionCarta(motivo=contradicciones[0][1], necesita_revision=True)

        return None

    async def _finalizar(self, card: Card, reconocido: Recognition) -> ResolucionCarta:
        """Última parada antes del éxito: si la carta no trae `dex_number`
        de TCGdex, intenta inferirlo de `species`/`dex_number` validando
        contra `app.pokemon`. Una contradicción ahí también rechaza toda la
        resolución -- no es un detalle menor, es la misma regla de "dos
        señales que se contradicen no confirman"."""
        if card.dex_number is None:
            especie = await self._resolver_especie(reconocido)
            if especie is _CONTRADICCION:
                return ResolucionCarta(
                    motivo=(
                        f"el modelo dijo especie «{reconocido.species}» dex "
                        f"{reconocido.dex_number}, pero ese número de Pokédex no corresponde: "
                        "señales contradictorias"
                    ),
                    necesita_revision=True,
                )
            if isinstance(especie, int):
                with self._conn_factory() as conn:
                    catalog_repository.set_inferred_dex_number(conn, card.id, especie)
                    card = catalog_repository.get_card(conn, card.id)

        return ResolucionCarta(card=card, motivo=_motivo_exito(reconocido), necesita_revision=False)

    async def _buscar_set(self, set_name: str):
        objetivo = set_name.strip().casefold()
        for set_ref in await self._catalog.list_sets():
            if set_ref.name.strip().casefold() == objetivo:
                return set_ref
        return None

    async def _resolver_especie(self, reconocido: Recognition):
        """Devuelve el `dex_number` a inferir (int), `_CONTRADICCION` si las
        dos señales del modelo (especie, dex_number) no coinciden con
        `app.pokemon`, o `None` si no hay suficiente información para
        decidir nada (Entrenador/Energía, o dex fuera de 1..151 -- fuera de
        alcance, no un error)."""
        dex_number = reconocido.dex_number
        species = reconocido.species
        if dex_number is None or not species:
            return None
        if not (DEX_MIN <= dex_number <= DEX_MAX):
            return None

        with self._conn_factory() as conn:
            row = conn.execute(_SELECT_POKEMON_NAME, {"dex_number": dex_number}).fetchone()
        if row is None:
            # app.pokemon todavía no tiene esa fila (ej. antes del primer
            # import del Excel) -- no es una contradicción del modelo, es
            # que no hay con qué validar todavía.
            return None

        if _normalize_name(species) == _normalize_name(row["name"]):
            return dex_number
        return _CONTRADICCION


def _motivo_exito(reconocido: Recognition) -> str:
    if reconocido.needs_review or reconocido.confidence < CONFIDENCE_THRESHOLD:
        return "el modelo dudó de la lectura, pero el catálogo confirma esta carta"
    return "identificado y validado contra el catálogo"


class _Contradiccion:
    """Sentinel: distingue "no hay info para decidir" (`None`) de "las dos
    señales se contradicen" sin abusar de excepciones para control de flujo."""


_CONTRADICCION = _Contradiccion()
