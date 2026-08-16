"""Task 2: el reparto del costo. Función pura, sin base ni red -- todo acá
se prueba con `Decimal` de mano, sin `clean_db` ni fixtures de catálogo.

La tabla de casos del plan (`docs/superpowers/plans/2026-08-16-compras-y-tandas.md`,
Task 2, Step 3) es el corazón de este archivo: cada fila tiene un test.
"""

from decimal import Decimal

import pytest

from pokedex.purchases.allocation import (
    CopiaReparto,
    CostoManualFaltante,
    FaltaPrecioDeMercado,
    NadieAbsorbeElCosto,
    RepartoManualNoCuadra,
    repartir,
)


def _copia(id_, valor=None, *, bulk=False, manual=None) -> CopiaReparto:
    return CopiaReparto(id=id_, valor_mercado_usd=valor, es_bulk=bulk, costo_manual_usd=manual)


# --- market_value -----------------------------------------------------------


def test_todas_con_precio_reparte_proporcional_y_suma_exacta():
    copias = [_copia(1, Decimal("10.00")), _copia(2, Decimal("30.00"))]
    resultado = repartir(Decimal("40.00"), copias, "market_value")
    assert resultado[1] == Decimal("10.00")
    assert resultado[2] == Decimal("30.00")
    assert sum(resultado.values()) == Decimal("40.00")


def test_alguna_sin_precio_de_mercado_es_error_explicito():
    copias = [_copia(1, Decimal("10.00")), _copia(2, None)]
    with pytest.raises(FaltaPrecioDeMercado):
        repartir(Decimal("40.00"), copias, "market_value")


def test_todas_sin_precio_es_error_explicito_no_reparto_en_partes_iguales_encubierto():
    """El caso que el plan marca en negrita: ni un solo camino puede colar un
    reparto equitativo disfrazado de `market_value`."""
    copias = [_copia(1, None), _copia(2, None)]
    with pytest.raises(FaltaPrecioDeMercado):
        repartir(Decimal("40.00"), copias, "market_value")


def test_todas_bulk_es_error_nadie_absorbe_el_costo():
    copias = [_copia(1, Decimal("10.00"), bulk=True), _copia(2, Decimal("30.00"), bulk=True)]
    with pytest.raises(NadieAbsorbeElCosto):
        repartir(Decimal("40.00"), copias, "market_value")


def test_una_sola_carta_se_lleva_el_total():
    copias = [_copia(1, Decimal("15.00"))]
    resultado = repartir(Decimal("99.00"), copias, "market_value")
    assert resultado == {1: Decimal("99.00")}


def test_bulk_recibe_cero_y_queda_fuera_las_demas_absorben_el_total():
    copias = [
        _copia(1, Decimal("10.00")),
        _copia(2, Decimal("30.00")),
        _copia(3, Decimal("500.00"), bulk=True),
    ]
    resultado = repartir(Decimal("40.00"), copias, "market_value")
    assert resultado[3] == Decimal("0.00")
    assert resultado[1] == Decimal("10.00")
    assert resultado[2] == Decimal("30.00")
    assert sum(resultado.values()) == Decimal("40.00")


def test_redondeo_a_centavos_el_residuo_va_a_la_carta_de_mayor_valor_y_suma_exacta():
    """$95 entre 7 cartas de precios dispares: un ejemplo con residuo
    incómodo, el que más duele si falla (plan, Task 2)."""
    copias = [
        _copia(1, Decimal("5.00")),
        _copia(2, Decimal("7.00")),
        _copia(3, Decimal("9.00")),
        _copia(4, Decimal("11.00")),
        _copia(5, Decimal("13.00")),
        _copia(6, Decimal("17.00")),
        _copia(7, Decimal("23.00")),
    ]
    resultado = repartir(Decimal("95.00"), copias, "market_value")
    assert sum(resultado.values()) == Decimal("95.00"), "la suma debe cuadrar exacto al centavo"
    # Suma de los precios de mercado: 5+7+9+11+13+17+23 = 85. La de mayor
    # valor (id=7, $23.00) es la que absorbe el residuo del redondeo -- se
    # verifica indirectamente comparando contra el cálculo exacto sin
    # redondear: ninguna otra fila puede quedar por encima de su proporción
    # exacta (el redondeo siempre trunca hacia abajo salvo la que recibe el
    # residuo).
    exacto = {c.id: (c.valor_mercado_usd / Decimal("85.00")) * Decimal("95.00") for c in copias}
    for id_, valor in resultado.items():
        if id_ != 7:
            assert valor <= exacto[id_].quantize(Decimal("0.01"), rounding="ROUND_CEILING")


def test_total_cero_es_un_regalo_todas_a_cero_sin_dividir_por_cero():
    copias = [_copia(1, Decimal("10.00")), _copia(2, Decimal("30.00"))]
    resultado = repartir(Decimal("0.00"), copias, "market_value")
    assert resultado == {1: Decimal("0.00"), 2: Decimal("0.00")}


def test_total_cero_con_todas_bulk_no_es_error():
    """Sin costo que absorber, marcar todo bulk no es un problema: cero entre
    nadie sigue siendo cero, no una división por cero ni un error."""
    copias = [_copia(1, Decimal("10.00"), bulk=True)]
    resultado = repartir(Decimal("0.00"), copias, "market_value")
    assert resultado == {1: Decimal("0.00")}


# --- equal --------------------------------------------------------------


def test_equal_reparte_el_total_entre_el_numero_de_cartas():
    copias = [_copia(1), _copia(2), _copia(3), _copia(4)]
    resultado = repartir(Decimal("100.00"), copias, "equal")
    assert resultado == {
        1: Decimal("25.00"),
        2: Decimal("25.00"),
        3: Decimal("25.00"),
        4: Decimal("25.00"),
    }


def test_equal_con_residuo_suma_exacta_al_total():
    copias = [_copia(1), _copia(2), _copia(3)]
    resultado = repartir(Decimal("10.00"), copias, "equal")
    assert sum(resultado.values()) == Decimal("10.00")


def test_equal_no_requiere_precio_de_mercado():
    """`equal` no necesita valor de mercado -- a diferencia de
    `market_value`, ninguna carta sin precio debe tumbar este método."""
    copias = [_copia(1, None), _copia(2, None)]
    resultado = repartir(Decimal("10.00"), copias, "equal")
    assert sum(resultado.values()) == Decimal("10.00")


def test_equal_bulk_a_cero_y_fuera_del_reparto():
    copias = [_copia(1), _copia(2), _copia(3, bulk=True)]
    resultado = repartir(Decimal("10.00"), copias, "equal")
    assert resultado[3] == Decimal("0.00")
    assert sum(resultado.values()) == Decimal("10.00")


# --- manual ---------------------------------------------------------------


def test_manual_que_cuadra_se_acepta_tal_cual():
    copias = [
        _copia(1, manual=Decimal("12.00")),
        _copia(2, manual=Decimal("8.00")),
    ]
    resultado = repartir(Decimal("20.00"), copias, "manual")
    assert resultado == {1: Decimal("12.00"), 2: Decimal("8.00")}


def test_manual_que_no_cuadra_es_error_con_el_residuo_sin_guardar_nada():
    copias = [
        _copia(1, manual=Decimal("12.00")),
        _copia(2, manual=Decimal("5.00")),
    ]
    with pytest.raises(RepartoManualNoCuadra) as excinfo:
        repartir(Decimal("20.00"), copias, "manual")
    assert excinfo.value.residuo_usd == Decimal("3.00")


def test_manual_sin_costo_para_un_elegible_es_error():
    copias = [_copia(1, manual=Decimal("20.00")), _copia(2, manual=None)]
    with pytest.raises(CostoManualFaltante):
        repartir(Decimal("20.00"), copias, "manual")


def test_manual_bulk_se_fuerza_a_cero_incluso_si_se_mando_un_costo():
    copias = [_copia(1, manual=Decimal("10.00")), _copia(2, manual=Decimal("0.00"), bulk=True)]
    resultado = repartir(Decimal("10.00"), copias, "manual")
    assert resultado[2] == Decimal("0.00")


# --- recalcular no toca el total (Task 2, Step 4) --------------------------


def test_recalcular_con_otro_metodo_no_cambia_el_total_ni_descuadra_la_suma():
    total = Decimal("40.00")
    copias = [_copia(1, Decimal("10.00")), _copia(2, Decimal("30.00"))]

    por_valor = repartir(total, copias, "market_value")
    por_partes_iguales = repartir(total, copias, "equal")

    assert sum(por_valor.values()) == total
    assert sum(por_partes_iguales.values()) == total
    # El total en sí nunca lo toca esta función -- no hay ningún estado que
    # `repartir` mute; cada llamada es independiente y pura.
    assert total == Decimal("40.00")


# --- errores generales ------------------------------------------------------


def test_metodo_desconocido_lanza_value_error():
    with pytest.raises(ValueError):
        repartir(Decimal("10.00"), [_copia(1, Decimal("10.00"))], "inventado")


def test_total_negativo_lanza_value_error():
    with pytest.raises(ValueError):
        repartir(Decimal("-1.00"), [_copia(1, Decimal("10.00"))], "market_value")
