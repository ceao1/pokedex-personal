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
  const dex = String(pokemon.dex_number).padStart(3, "0");

  return (
    <article
      className={`${styles.pocket} ${conseguido ? styles.owned : styles.hunting}`}
      style={{ "--delay": `${index * 20}ms` } as React.CSSProperties}
      aria-label={
        conseguido
          ? `${pokemon.name}, número ${dex}, en el binder`
          : `${pokemon.name}, número ${dex}, todavía no lo tienes`
      }
    >
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
        {pokemon.primary_price_usd !== null && (
          <span className={styles.price}>${pokemon.primary_price_usd.toFixed(2)}</span>
        )}
      </footer>
    </article>
  );
}
