"""Valida la respuesta del modelo de reconocimiento contra el catálogo real.

Acá es donde el reconocimiento se gana el derecho a ser creído (spec §5.2):
solo se acepta si `(set, número)` resuelve a una carta real, y el nombre que
dijo el modelo coincide con el de esa carta. Todo lo demás -- set inexistente,
número que se contradice con el `cardCount` del set, número inexistente,
`needs_review` del propio modelo, confianza baja, nombre que no coincide --
termina en revisión manual sin carta, nunca en una adivinanza.

También intenta rellenar `Card.dex_number` cuando falta (cartas de
entrenador tipo "Erika's Gloom", que TCGdex no etiqueta con `dexId`) usando
`species`/`dex_number` del reconocimiento -- pero solo si esa inferencia
coincide con `app.pokemon`, la fuente autoritativa de los 151. Si las dos
señales se contradicen, no se adivina cuál vale: revisión manual.
"""

import re
import unicodedata
from collections.abc import Callable
from contextlib import AbstractContextManager

from psycopg import Connection
from pydantic import BaseModel

from pokedex.catalog import repository as catalog_repository
from pokedex.catalog.models import Card, SetRef
from pokedex.catalog.ports import CatalogPort

from .models import Recognition

ConnFactory = Callable[[], AbstractContextManager[Connection]]

# Piloteado, no medido: 0.7 es un punto de partida razonable para una
# primera versión, no un número calibrado contra fotos reales. El spec
# (§5.2) pide justamente ese piloto para ajustarlo; hasta entonces, ante la
# duda, revisión manual cuesta menos que un dato falso guardado.
CONFIDENCE_THRESHOLD = 0.7

# Rango de la Pokédex que cubre este proyecto (spec: "los 151 originales").
# Un dex_number fuera de este rango no es un error del modelo -- es una
# carta fuera de alcance -- así que no se infiere ni se marca revisión.
DEX_MIN, DEX_MAX = 1, 151

_NUMBER_RE = re.compile(r"^\s*([^\s/]+)\s*/\s*(\d+)\s*$")

# Sufijos de carta que no forman parte del nombre de la especie/Pokémon.
# Se despojan de ambos lados antes de comparar -- así "Charizard" (lo que
# dijo el modelo) coincide con "Charizard ex" (el nombre de la carta) sin
# hacer coincidencia parcial agresiva sobre el resto del nombre.
_SUFFIX_RE = re.compile(r"\s+(ex|gx|v|vmax|vstar|vunion|prime|break|lv\.x)$", re.IGNORECASE)

_SELECT_POKEMON_NAME = "select name from app.pokemon where dex_number = %(dex_number)s"


class ResolucionCarta(BaseModel):
    card: Card | None = None
    motivo: str
    necesita_revision: bool = False


def _normalize_name(name: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    resultado = sin_acentos.strip().casefold()
    # Repetido: un nombre podría traer más de un sufijo pegado (no debería,
    # pero es gratis cubrirlo) y cada pasada solo saca uno.
    anterior = None
    while anterior != resultado:
        anterior = resultado
        resultado = _SUFFIX_RE.sub("", resultado).strip()
    return resultado


def _normalize_number_part(value: str) -> str:
    return value.strip().casefold().lstrip("0") or "0"


def _parse_number(number: str) -> tuple[str, str] | None:
    match = _NUMBER_RE.match(number)
    if match is None:
        return None
    return match.group(1), match.group(2)


class CardResolver:
    def __init__(self, catalog: CatalogPort, conn_factory: ConnFactory) -> None:
        self._catalog = catalog
        self._conn_factory = conn_factory

    async def resolver(self, reconocido: Recognition) -> ResolucionCarta:
        if reconocido.needs_review:
            return ResolucionCarta(
                motivo="el modelo marcó la lectura como dudosa", necesita_revision=True
            )
        if reconocido.confidence < CONFIDENCE_THRESHOLD:
            return ResolucionCarta(
                motivo=f"confianza {reconocido.confidence:.2f} por debajo del umbral "
                f"({CONFIDENCE_THRESHOLD})",
                necesita_revision=True,
            )
        if not reconocido.set_name or not reconocido.number:
            return ResolucionCarta(
                motivo="el modelo no devolvió set o número de colección", necesita_revision=True
            )

        set_ref = await self._buscar_set(reconocido.set_name)
        if set_ref is None:
            return ResolucionCarta(
                motivo=f"el set «{reconocido.set_name}» no existe en el catálogo",
                necesita_revision=True,
            )

        parsed = _parse_number(reconocido.number)
        if parsed is None:
            return ResolucionCarta(
                motivo=f"el número «{reconocido.number}» no tiene el formato N/total",
                necesita_revision=True,
            )
        numerator, denominator = parsed
        if set_ref.total is not None and int(denominator) != set_ref.total:
            return ResolucionCarta(
                motivo=(
                    f"el set «{set_ref.name}» tiene {set_ref.total} cartas, no {denominator}: "
                    "el modelo se contradijo a sí mismo"
                ),
                necesita_revision=True,
            )

        cartas = await self._catalog.list_set_cards(set_ref.id)
        objetivo = _normalize_number_part(numerator)
        coincidencia = next(
            (c for c in cartas if _normalize_number_part(c.local_id) == objetivo), None
        )
        if coincidencia is None:
            return ResolucionCarta(
                motivo=f"no existe la carta {numerator}/{denominator} en {set_ref.name}",
                necesita_revision=True,
            )

        if reconocido.name and _normalize_name(reconocido.name) != _normalize_name(
            coincidencia.name
        ):
            return ResolucionCarta(
                motivo=(
                    f"el modelo dijo «{reconocido.name}» pero el número apunta a "
                    f"«{coincidencia.name}»: señales contradictorias"
                ),
                necesita_revision=True,
            )

        card = await self._catalog.get_card(coincidencia.id)
        if card is None:
            return ResolucionCarta(
                motivo="no se pudo cargar la carta encontrada", necesita_revision=True
            )

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

        return ResolucionCarta(card=card, motivo="identificado y validado contra el catálogo")

    async def _buscar_set(self, set_name: str) -> SetRef | None:
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


class _Contradiccion:
    """Sentinel: distingue "no hay info para decidir" (`None`) de "las dos
    señales se contradicen" sin abusar de excepciones para control de flujo."""


_CONTRADICCION = _Contradiccion()
