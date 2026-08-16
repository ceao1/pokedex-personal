from decimal import Decimal

import pytest

from pokedex.catalog.models import CardRef
from pokedex.wishlist.models import ExcelOption, ExcelRow, GalleryRow
from pokedex.wishlist.resolver import VINTAGE_SETS, OptionResolver

SET_151 = "sv03.5"


class FakeCatalog:
    """CatalogPort falso con solo lo que el resolver usa."""

    def __init__(self):
        self.set_cards = {
            "base1": [
                CardRef(id="base1-4", local_id="4", name="Charizard"),
                CardRef(id="base1-44", local_id="44", name="Bulbasaur"),
            ],
            "base2": [CardRef(id="base2-1", local_id="1", name="Clefable")],
            "base3": [CardRef(id="base3-1", local_id="1", name="Aerodactyl")],
            "basep": [CardRef(id="basep-1", local_id="1", name="Pikachu")],
        }
        self.numero_calls = []

    async def find_by_set_and_number(self, set_id: str, local_id: str):
        self.numero_calls.append((set_id, local_id))
        if set_id == SET_151 and local_id in {"001", "011", "166"}:
            from pokedex.catalog.models import Card

            return Card(
                id=f"{SET_151}-{local_id}",
                name="X",
                set_id=SET_151,
                set_name="151",
                local_id=local_id,
                raw={},
            )
        return None

    async def get_card(self, card_id: str):
        return None

    async def list_set_cards(self, set_id: str):
        return self.set_cards.get(set_id, [])


def _row(dex, nombre, **opciones):
    return ExcelRow(
        dex_number=dex,
        pokemon_name=nombre,
        options=[
            ExcelOption(source_option=k, raw_text=v, reference_value_usd=Decimal("1.00"))
            for k, v in opciones.items()
        ],
    )


async def test_la_opcion_1_resuelve_por_numero_como_normal():
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(1, "Bulbasaur", opcion_1="Bulbasaur 001/165"))
    op1 = next(o for o in resueltas if o.source_option == "opcion_1")
    assert op1.card_id == "sv03.5-001"
    assert op1.variant_label == "normal"
    assert op1.auto_resolved is False, "resolver por número es determinístico, no heurístico"


async def test_el_numero_se_rellena_a_tres_digitos():
    fake = FakeCatalog()
    resolver = OptionResolver(fake)
    await resolver.resolve_row(_row(11, "Metapod", opcion_1="Metapod 011/165"))
    assert ("sv03.5", "011") in fake.numero_calls


async def test_la_opcion_2_reverse_apunta_a_la_misma_carta_que_la_1():
    """123 de las 151 filas son este caso."""
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(
        _row(11, "Metapod", opcion_1="Metapod 011/165", opcion_2="Reverse holo de 011/165")
    )
    op1 = next(o for o in resueltas if o.source_option == "opcion_1")
    op2 = next(o for o in resueltas if o.source_option == "opcion_2")
    assert op2.card_id == op1.card_id
    assert op1.variant_label == "normal"
    assert op2.variant_label == "reverse"


async def test_la_opcion_2_con_carta_distinta_resuelve_como_holo():
    """Las 28 Illustration/Special/Ultra Rare tienen una única variante holo."""
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(
        _row(1, "Bulbasaur", opcion_1="Bulbasaur 001/165", opcion_2="Bulbasaur 166/165")
    )
    op2 = next(o for o in resueltas if o.source_option == "opcion_2")
    assert op2.card_id == "sv03.5-166"
    assert op2.variant_label == "holo"


async def test_la_opcion_2_reverse_no_repite_la_consulta_al_catalogo():
    """Si la opción 1 ya resolvió, el reverse reusa ese card_id directamente
    en vez de volver a consultar el catálogo por el mismo número."""
    fake = FakeCatalog()
    resolver = OptionResolver(fake)
    await resolver.resolve_row(
        _row(11, "Metapod", opcion_1="Metapod 011/165", opcion_2="Reverse holo de 011/165")
    )
    assert fake.numero_calls == [("sv03.5", "011")], "no debe repetir la consulta del reverse"


async def test_resolve_gallery_row_holo_para_carta_propia():
    """Caso general: 'Bulbasaur 151 166/165' es una Illustration Rare propia,
    igual que la opción 2 no-reverse."""
    resolver = OptionResolver(FakeCatalog())
    resuelto = await resolver.resolve_gallery_row(
        GalleryRow(dex_number=1, pokemon_name="Bulbasaur", raw_text="Bulbasaur 151 166/165")
    )
    assert resuelto.card_id == "sv03.5-166"
    assert resuelto.variant_label == "holo"


async def test_resolve_gallery_row_detecta_reverse():
    """El texto real de la galería para Kadabra es
    'Kadabra 151 064/165 reverse holo': si se resolviera como 'holo' a
    secas, en vez de fusionarse con la fila que la opción 2 ya insertó como
    reverse crearía una fila nueva con una variante distinta -- exactamente
    la duplicación que este fix debía prevenir."""
    resolver = OptionResolver(FakeCatalog())
    resuelto = await resolver.resolve_gallery_row(
        GalleryRow(
            dex_number=11, pokemon_name="Metapod", raw_text="Metapod 151 011/165 reverse holo"
        )
    )
    assert resuelto.card_id == "sv03.5-011"
    assert resuelto.variant_label == "reverse"


async def test_resolve_gallery_row_sin_numero_queda_sin_resolver():
    resolver = OptionResolver(FakeCatalog())
    resuelto = await resolver.resolve_gallery_row(
        GalleryRow(dex_number=2, pokemon_name="Ivysaur", raw_text="Ivysaur Southern Islands")
    )
    assert resuelto.card_id is None


async def test_la_opcion_3_resuelve_por_nombre_dentro_del_set_vintage():
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(6, "Charizard", opcion_3="Charizard Base Set Holo"))
    op3 = next(o for o in resueltas if o.source_option == "opcion_3")
    assert op3.card_id == "base1-4"
    assert op3.variant_label == "unlimited"
    assert op3.auto_resolved is True, "vintage se resuelve por heurística y debe marcarse"


async def test_la_opcion_3_sin_holo_tambien_prefiere_unlimited():
    """La hoja Guía dice explícitamente que en vintage se compra Unlimited."""
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(6, "Charizard", opcion_3="Charizard Base Set"))
    op3 = next(o for o in resueltas if o.source_option == "opcion_3")
    assert op3.card_id == "base1-4"
    assert op3.variant_label == "unlimited"


async def test_un_nombre_que_no_esta_en_el_set_queda_sin_resolver():
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(9, "Blastoise", opcion_3="Blastoise Base Set"))
    op3 = next(o for o in resueltas if o.source_option == "opcion_3")
    assert op3.card_id is None
    assert op3.variant_label is None
    assert op3.raw_text == "Blastoise Base Set"


async def test_una_coincidencia_ambigua_en_vintage_queda_sin_resolver():
    """La regla es 'no adivinar': dos cartas con el mismo nombre en el mismo
    set no deben resolver a ninguna de las dos."""
    fake = FakeCatalog()
    fake.set_cards["base1"] = [
        CardRef(id="base1-4", local_id="4", name="Ditto"),
        CardRef(id="base1-9", local_id="9", name="Ditto"),
    ]
    resolver = OptionResolver(fake)
    resueltas = await resolver.resolve_row(_row(132, "Ditto", opcion_3="Ditto Base Set"))
    op3 = next(o for o in resueltas if o.source_option == "opcion_3")
    assert op3.card_id is None


async def test_un_texto_vintage_desconocido_queda_sin_resolver():
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(2, "Ivysaur", opcion_3="Ivysaur Southern Islands"))
    op3 = next(o for o in resueltas if o.source_option == "opcion_3")
    assert op3.card_id is None


async def test_el_valor_de_referencia_se_conserva_resuelva_o_no():
    resolver = OptionResolver(FakeCatalog())
    resueltas = await resolver.resolve_row(_row(9, "Blastoise", opcion_3="Blastoise Base Set"))
    assert all(o.reference_value_usd == Decimal("1.00") for o in resueltas)


def test_el_mapa_de_sets_vintage_cubre_las_siete_formas():
    assert set(VINTAGE_SETS) == {
        "Base Set",
        "Base Set Holo",
        "Jungle",
        "Jungle Holo",
        "Fossil",
        "Fossil Holo",
        "Black Star Promo",
    }
    assert VINTAGE_SETS["Base Set Holo"] == ("base1", True)
    assert VINTAGE_SETS["Jungle"] == ("base2", False)
    assert VINTAGE_SETS["Fossil"] == ("base3", False)
    assert VINTAGE_SETS["Black Star Promo"] == ("basep", False)


@pytest.mark.parametrize("texto", ["Base Set", "Jungle Holo", "Fossil"])
def test_los_ids_de_set_son_los_verificados(texto):
    set_id, _ = VINTAGE_SETS[texto]
    assert set_id in {"base1", "base2", "base3", "basep"}
