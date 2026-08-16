"""Resolución de las opciones del Excel contra el catálogo.

Las opciones 1 y 2 traen número de colección y resuelven de forma
determinística contra el set 151. La opción 3 es texto vintage con solo siete
formas posibles, resueltas por nombre dentro del set correspondiente. La
opción 4 son nueve casos sueltos de sets modernos.
"""

import re
from decimal import Decimal

import httpx
from pydantic import BaseModel

from pokedex.catalog.models import CardRef
from pokedex.catalog.ports import CatalogPort
from pokedex.catalog.variants import VariantLabel

from .models import ExcelOption, ExcelRow, GalleryRow

SET_151 = "sv03.5"

NUMERO_RE = re.compile(r"(\d{1,3})\s*/\s*165\b")
REVERSE_RE = re.compile(r"^\s*reverse\s+holo\s+de\b", re.IGNORECASE)
# La galería no repite el formato de la opción 2 ("Reverse holo de NNN/165");
# escribe el número primero y "reverse holo" como sufijo suelto (ej.
# "Kadabra 151 064/165 reverse holo"), así que basta con la palabra.
GALLERY_REVERSE_RE = re.compile(r"\breverse\b", re.IGNORECASE)

# Texto de la opción 3 -> (set de TCGdex, el texto pedía holo)
# Exhaustivo: estas siete formas cubren las 151 filas del Excel.
VINTAGE_SETS: dict[str, tuple[str, bool]] = {
    "Base Set": ("base1", False),
    "Base Set Holo": ("base1", True),
    "Jungle": ("base2", False),
    "Jungle Holo": ("base2", True),
    "Fossil": ("base3", False),
    "Fossil Holo": ("base3", True),
    "Black Star Promo": ("basep", False),
}

# El catálogo no pudo responder -- distinto de que haya respondido "no
# existe". `find_by_set_and_number`/`list_set_cards`/`get_card` propagan
# estas excepciones cuando la red falla; un 5xx (el servidor respondió, mal)
# cuenta igual. Un 404 no entra acá: la adaptación de TCGdex ya lo traduce a
# `None`, que sí es una respuesta real (ver `_resolve_numbered`).
CATALOG_NETWORK_ERRORS = (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout)


def es_error_de_servidor(exc: httpx.HTTPStatusError) -> bool:
    return exc.response.status_code >= 500


class ResolvedOption(BaseModel):
    source_option: str
    raw_text: str
    card_id: str | None = None
    variant_label: str | None = None
    reference_value_usd: Decimal | None = None
    auto_resolved: bool = False
    # El catálogo no pudo responder (timeout, error de conexión, 5xx) a esta
    # pregunta -- distinto de `card_id is None` por una respuesta real de
    # "no existe". El llamador (ImportService) no debe guardar nada cuando
    # esto es True: guardarlo como no resuelto duplicaría la fila el día que
    # una corrida posterior sí logre resolver (ver service.py).
    unreachable: bool = False


class OptionResolver:
    def __init__(self, catalog: CatalogPort) -> None:
        self._catalog = catalog
        self._set_cache: dict[str, list[CardRef]] = {}

    async def resolve_row(self, row: ExcelRow) -> list[ResolvedOption]:
        resueltas: list[ResolvedOption] = []
        card_id_opcion_1: str | None = None

        for option in row.options:
            if option.source_option == "opcion_1":
                resolved = await self._resolve_numbered(option, VariantLabel.NORMAL)
                card_id_opcion_1 = resolved.card_id
            elif option.source_option == "opcion_2":
                resolved = await self._resolve_option_2(option, card_id_opcion_1)
            elif option.source_option == "opcion_3":
                resolved = await self._resolve_vintage(option, row.pokemon_name)
            else:
                resolved = ResolvedOption(
                    source_option=option.source_option,
                    raw_text=option.raw_text,
                    reference_value_usd=option.reference_value_usd,
                )
            resueltas.append(resolved)
        return resueltas

    async def _resolve_numbered(self, option: ExcelOption, variant: VariantLabel) -> ResolvedOption:
        match = NUMERO_RE.search(option.raw_text)
        base = ResolvedOption(
            source_option=option.source_option,
            raw_text=option.raw_text,
            reference_value_usd=option.reference_value_usd,
        )
        if match is None:
            return base
        # El Excel escribe "1/165" y "001/165" indistintamente; TCGdex usa
        # el localId con tres dígitos en este set.
        local_id = match.group(1).zfill(3)
        try:
            card = await self._catalog.find_by_set_and_number(SET_151, local_id)
        except CATALOG_NETWORK_ERRORS:
            base.unreachable = True
            return base
        except httpx.HTTPStatusError as exc:
            if not es_error_de_servidor(exc):
                raise
            base.unreachable = True
            return base
        if card is None:
            return base
        base.card_id = card.id
        base.variant_label = variant.value
        return base

    async def _resolve_option_2(
        self, option: ExcelOption, card_id_opcion_1: str | None
    ) -> ResolvedOption:
        """Dos casos: el reverse de la carta de la opción 1, o una carta propia.

        En 123 de las 151 filas el texto es "Reverse holo de NNN/165" y apunta
        a la misma carta que la opción 1. En las otras 28 es una Illustration,
        Ultra o Special Illustration Rare, que en TCGdex tiene una única
        variante `holo`.
        """
        if REVERSE_RE.match(option.raw_text):
            if card_id_opcion_1 is not None:
                # El número del texto del reverse es el mismo de la opción 1;
                # si aquélla ya resolvió, reusamos su card_id directamente y
                # nos ahorramos una consulta redundante al catálogo.
                return ResolvedOption(
                    source_option=option.source_option,
                    raw_text=option.raw_text,
                    card_id=card_id_opcion_1,
                    variant_label=VariantLabel.REVERSE.value,
                    reference_value_usd=option.reference_value_usd,
                )
            # La opción 1 no resolvió (número no encontrado, o el catálogo
            # estaba inalcanzable); como último recurso, intentamos resolver
            # el reverse por su propio número.
            return await self._resolve_numbered(option, VariantLabel.REVERSE)
        return await self._resolve_numbered(option, VariantLabel.HOLO)

    async def resolve_gallery_row(self, gallery_row: GalleryRow) -> ResolvedOption:
        """La galería solo trae texto y, a veces, un número de colección del
        set 151 (ej. "Bulbasaur 151 166/165"). La mayoría son Illustration o
        Special Illustration Rare con una única variante `holo` en TCGdex —
        el mismo caso que la opción 2 no-reverse — pero al menos una fila
        real (Kadabra: "Kadabra 151 064/165 reverse holo") nombra el reverse
        de la carta normal, que ya insertó la opción 2 como `reverse`; si se
        etiquetara como `holo` a secas no fusionaría con esa fila y crearía
        una nueva con una variante distinta. Se reusa `_resolve_numbered` en
        vez de escribir un segundo parser."""
        option = ExcelOption(
            source_option="galeria",
            raw_text=gallery_row.raw_text,
            reference_value_usd=gallery_row.reference_value_usd,
        )
        variant = (
            VariantLabel.REVERSE
            if GALLERY_REVERSE_RE.search(gallery_row.raw_text)
            else VariantLabel.HOLO
        )
        return await self._resolve_numbered(option, variant)

    async def _resolve_vintage(self, option: ExcelOption, pokemon_name: str) -> ResolvedOption:
        base = ResolvedOption(
            source_option=option.source_option,
            raw_text=option.raw_text,
            reference_value_usd=option.reference_value_usd,
        )
        sufijo = self._vintage_suffix(option.raw_text, pokemon_name)
        if sufijo is None:
            return base
        set_id, _pide_holo = VINTAGE_SETS[sufijo]

        try:
            cards = await self._set_cards(set_id)
        except CATALOG_NETWORK_ERRORS:
            base.unreachable = True
            return base
        except httpx.HTTPStatusError as exc:
            if not es_error_de_servidor(exc):
                raise
            base.unreachable = True
            return base

        coincidencias = [c for c in cards if c.name.casefold() == pokemon_name.casefold()]
        if len(coincidencias) != 1:
            # Cero coincidencias, o varias impresiones del mismo Pokémon en el
            # set: no adivinamos cuál, queda para revisión manual.
            return base

        base.card_id = coincidencias[0].id
        # La hoja Guía es explícita: en vintage se compra la Unlimited.
        base.variant_label = VariantLabel.UNLIMITED.value
        base.auto_resolved = True
        return base

    @staticmethod
    def _vintage_suffix(raw_text: str, pokemon_name: str) -> str | None:
        resto = raw_text.strip()
        if resto.casefold().startswith(pokemon_name.casefold()):
            resto = resto[len(pokemon_name) :].strip()
        return resto if resto in VINTAGE_SETS else None

    async def _set_cards(self, set_id: str) -> list[CardRef]:
        """Puede lanzar `CATALOG_NETWORK_ERRORS` o `httpx.HTTPStatusError`
        (5xx): a propósito, no se atrapan acá. Solo se cachean los éxitos --
        cachear una falla congelaría "inalcanzable" para el resto de la
        corrida aunque una llamada posterior al mismo set sí hubiera
        funcionado, y este módulo no reintenta ni recuerda fallas (esa
        decisión es de quien llama, no de este cache)."""
        if set_id not in self._set_cache:
            self._set_cache[set_id] = await self._catalog.list_set_cards(set_id)
        return self._set_cache[set_id]
