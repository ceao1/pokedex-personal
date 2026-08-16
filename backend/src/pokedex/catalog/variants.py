"""Parseo de `variants_detailed` y elección de la variante que el usuario marcó.

Una carta puede tener varias entradas del mismo `type`, distinguidas por
`stamp` (ej. `set-logo`) o `foil` (ej. `cosmos`). Son cartas distintas con
precios muy distintos, así que la desambiguación importa: en Bulbasaur
sv03.5-001 la entrada con sello cuesta 280 veces más que la común.
"""

from datetime import datetime
from enum import StrEnum

from .models import CardVariant
from .pricing import extract_price_usd


class VariantLabel(StrEnum):
    NORMAL = "normal"
    REVERSE = "reverse"
    HOLO = "holo"
    FIRST_EDITION = "first_edition"
    SHADOWLESS = "shadowless"
    UNLIMITED = "unlimited"


def parse_variants(payload: dict, captured_at: datetime) -> list[CardVariant]:
    variants: list[CardVariant] = []
    for entry in payload.get("variants_detailed", []):
        price = extract_price_usd(entry)
        variants.append(
            CardVariant(
                id=entry["variantId"],
                type=entry["type"],
                subtype=entry.get("subtype"),
                stamp=entry.get("stamp") or [],
                foil=entry.get("foil"),
                size=entry.get("size"),
                price_usd=price,
                # El check de la base exige que ambos sean nulos o ninguno.
                price_captured_at=captured_at if price is not None else None,
                raw=entry,
            )
        )
    return variants


def _matches(variant: CardVariant, label: VariantLabel) -> bool:
    """Autoridad sobre qué significa cada `VariantLabel`.

    `wishlist/repository.py` (`_VARIANTE_PREFERIDA`) traduce este `match` a
    un `case` de SQL para resolver el precio de un item de wishlist sin
    traer todas las variantes a Python. Si esta función cambia -- una
    etiqueta nueva, o el criterio de una existente --, ese `case` tiene que
    cambiar junto con ella; que no diverjan es lo que evita que un
    `variant_label` deje de encontrar precio en el join.
    """
    match label:
        case VariantLabel.NORMAL:
            return variant.type == "normal"
        case VariantLabel.REVERSE:
            return variant.type == "reverse"
        case VariantLabel.HOLO:
            return variant.type == "holo" and variant.subtype is None
        case VariantLabel.FIRST_EDITION:
            return "1st-edition" in variant.stamp
        case VariantLabel.SHADOWLESS:
            return variant.subtype == "shadowless" and "1st-edition" not in variant.stamp
        case VariantLabel.UNLIMITED:
            return variant.subtype == "unlimited"
    return False


def _specificity(variant: CardVariant) -> tuple[int, int, int]:
    """Menor es más preferible: sin sello, sin foil, tamaño estándar."""
    return (
        1 if variant.stamp else 0,
        1 if variant.foil else 0,
        0 if variant.size in (None, "standard") else 1,
    )


def pick_variant(variants: list[CardVariant], label: VariantLabel) -> CardVariant | None:
    """La variante que corresponde al chip que tocó el usuario.

    Si quedan varias candidatas, gana la menos exótica. Cuando ni así se
    desempata, el llamador debe mandar el ejemplar a revisión manual.
    """
    candidatas = [v for v in variants if _matches(v, label)]
    if not candidatas:
        return None
    return min(candidatas, key=_specificity)
