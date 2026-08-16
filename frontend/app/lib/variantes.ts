import type { Variant, VariantLabel } from "./types";

/** Los sets vintage (1999-2003) son los únicos con chips "1st Edition",
 * "Shadowless" y "Unlimited" (spec §6.2). Todo lo demás es moderno.
 * Compartido por `/registrar` y `/compras/nueva`: la variante sigue siendo
 * del humano en las dos pantallas, y las reglas de qué chip corresponde a
 * qué fila de `card_variant` no deben divergir entre ellas. */
export const SETS_WOTC = new Set(["base1", "base2", "base3", "basep"]);

export const CHIPS_MODERNOS: { label: VariantLabel; texto: string }[] = [
  { label: "normal", texto: "Normal" },
  { label: "reverse", texto: "Reverse" },
  { label: "holo", texto: "Holo" },
];

export const CHIPS_VINTAGE: { label: VariantLabel; texto: string }[] = [
  { label: "first_edition", texto: "1st Edition" },
  { label: "shadowless", texto: "Shadowless" },
  { label: "unlimited", texto: "Unlimited" },
];

/** Paso 1 del mapeo de chip a variante (spec §6.2): qué fila de
 * `card_variant` corresponde al chip que tocó el usuario. */
function coincideVariante(variante: Variant, label: VariantLabel): boolean {
  switch (label) {
    case "normal":
      return variante.type === "normal";
    case "reverse":
      return variante.type === "reverse";
    case "holo":
      return variante.type === "holo" && variante.subtype === null;
    case "first_edition":
      return variante.stamp.includes("1st-edition");
    case "shadowless":
      return variante.subtype === "shadowless" && !variante.stamp.includes("1st-edition");
    case "unlimited":
      return variante.subtype === "unlimited";
    default:
      return false;
  }
}

/** Paso 2: si quedó más de una fila candidata, gana la menos exótica.
 * `VariantOut` no trae `size` (a diferencia de `variants.py` en el
 * backend), pero `stamp` + `foil` ya alcanzan para el caso que importa:
 * Bulbasaur sv03.5-001 tiene dos entradas `normal` y la que lleva
 * `stamp: ["set-logo"]` cuesta 280 veces más que la común. */
function especificidad(variante: Variant): [number, number] {
  return [variante.stamp.length > 0 ? 1 : 0, variante.foil ? 1 : 0];
}

export function elegirVariante(variantes: Variant[], label: VariantLabel): Variant | null {
  const candidatas = variantes.filter((v) => coincideVariante(v, label));
  if (candidatas.length === 0) return null;
  return candidatas.reduce((mejor, actual) => {
    const [s1, f1] = especificidad(mejor);
    const [s2, f2] = especificidad(actual);
    if (s2 < s1) return actual;
    if (s2 === s1 && f2 < f1) return actual;
    return mejor;
  });
}
