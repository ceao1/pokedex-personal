"use client";

import { useState } from "react";
import type { Pokemon } from "../lib/types";
import { Pocket } from "./Pocket";
import { Rail } from "./Rail";
import styles from "./Binder.module.css";

const POR_PAGINA = 9;

export function Binder({ pokedex }: { pokedex: Pokemon[] }) {
  const [pagina, setPagina] = useState(0);
  const paginas = Math.ceil(pokedex.length / POR_PAGINA);

  const bolsillos: (Pokemon | null)[] = Array.from({ length: POR_PAGINA }, (_, i) => {
    return pokedex[pagina * POR_PAGINA + i] ?? null;
  });

  const conseguidos = pokedex.filter((p) => p.wishlist_count > 0).length;

  return (
    <div className={styles.shell}>
      <Rail total={pokedex.length} conseguidos={conseguidos} invertidoUsd={0} />

      <main className={styles.spread}>
        <div className={styles.grid} key={pagina}>
          {bolsillos.map((pokemon, i) => (
            <Pocket key={pokemon?.dex_number ?? `hueco-${i}`} pokemon={pokemon} index={i} />
          ))}
        </div>

        <nav className={styles.pager} aria-label="Páginas del binder">
          <button
            className={styles.turn}
            onClick={() => setPagina((p) => Math.max(0, p - 1))}
            disabled={pagina === 0}
          >
            ‹ Anterior
          </button>
          <p className={styles.pageNumber}>
            Página <b>{pagina + 1}</b> de {paginas}
          </p>
          <button
            className={styles.turn}
            onClick={() => setPagina((p) => Math.min(paginas - 1, p + 1))}
            disabled={pagina >= paginas - 1}
          >
            Siguiente ›
          </button>
        </nav>
      </main>
    </div>
  );
}
