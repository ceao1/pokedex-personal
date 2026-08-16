from pydantic import BaseModel, Field, field_validator


class Recognition(BaseModel):
    """Lo que el modelo de visión cree haber leído en la foto de una carta.

    Nunca se acepta tal cual (spec §5.2): `resolver.CardResolver` es quien
    decide si esto se gana el derecho a convertirse en una `Card` real.
    """

    name: str | None = None
    set_name: str | None = None
    # El código impreso junto al número en la carta física (`ASC`, `BS`,
    # `JU`) -- lo que el modelo puede *leer*, a diferencia de `set_name`,
    # que le pide *recordar* un nombre que muchas veces ni siquiera aparece
    # impreso. Es la señal más fuerte del resolutor (ver
    # `recognition/resolver.py`): única entre 188 de los 218 sets del
    # catálogo. `null` si la carta no lo imprime o no se distingue --nunca
    # se deduce del nombre del set, porque eso volvería a ser memoria en
    # vez de lectura.
    set_code: str | None = None
    number: str | None = None
    rarity: str | None = None
    # Especie base y número de Pokédex nacional -- distintos de `name`, que es
    # el texto impreso en la carta ("Erika's Gloom", "M Venusaur EX"). Sirven
    # para inferir `Card.dex_number` cuando TCGdex no trae `dexId` (cartas de
    # entrenador como las "Erika's X"); `null` en ambos es el resultado
    # normal para Entrenador/Energía. Ver `recognition/resolver.py`.
    species: str | None = None
    dex_number: int | None = None
    confidence: float = 0.0
    needs_review: bool = True
    # JSON crudo que devolvió el modelo -- útil para depurar sin volver a
    # llamarlo. Nunca se sirve tal cual por HTTP (ver `routes/capture.py`).
    raw: dict = Field(default_factory=dict)

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        """Un modelo que devuelve `95` en vez de `0.95` no puede colarse por
        encima del umbral de `CardResolver` por un error de escala."""
        return max(0.0, min(1.0, value))
