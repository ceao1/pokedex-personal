import Link from "next/link";
import type { Pokemon } from "../lib/types";
import styles from "./Pocket.module.css";

type Props = {
  pokemon: Pokemon | null;
  index: number;
};

export function Pocket({ pokemon, index }: Props) {
  if (pokemon === null) {
    return <div className={`${styles.pocket} ${styles.blank}`} aria-hidden="true" />;
  }

  const conseguido = pokemon.owned_count > 0;
  const varios = pokemon.owned_count > 1;
  const dex = String(pokemon.dex_number).padStart(3, "0");

  const ariaCantidad =
    pokemon.owned_count === 0
      ? "todavía no lo tienes"
      : pokemon.owned_count === 1
        ? "tienes 1 ejemplar"
        : `tienes ${pokemon.owned_count} ejemplares`;

  return (
    <Link
      href={`/pokemon/${pokemon.dex_number}`}
      className={`${styles.pocket} ${conseguido ? styles.owned : styles.hunting}`}
      style={{ "--delay": `${index * 20}ms` } as React.CSSProperties}
      aria-label={`${pokemon.name}, número ${dex}, ${ariaCantidad}.`}
    >
      {/* Los cantos apilados asoman detrás de la carta cuando hay más de un
          ejemplar: como cartas metidas en la misma funda. Tope de dos,
          tenga cinco ejemplares o cincuenta -- el número ya lo dice. */}
      {varios && (
        <>
          <span className={styles.stackEdge2} aria-hidden="true" />
          <span className={styles.stackEdge1} aria-hidden="true" />
        </>
      )}

      <div className={styles.face}>
        {pokemon.primary_image_url ? (
          <img
            className={styles.card}
            src={pokemon.primary_image_url}
            alt=""
            loading="lazy"
          />
        ) : (
          <div className={styles.noCard}>
            <span>Sin carta asignada</span>
          </div>
        )}

        <span className={styles.sheen} aria-hidden="true" />

        <footer className={styles.plate}>
          <span className={styles.dex}>{dex}</span>
          <span className={styles.name}>{pokemon.name}</span>
          {varios && <span className={styles.count}>×{pokemon.owned_count}</span>}
          {pokemon.primary_price_usd !== null && (
            <span className={styles.price}>${pokemon.primary_price_usd.toFixed(2)}</span>
          )}
        </footer>
      </div>
    </Link>
  );
}
