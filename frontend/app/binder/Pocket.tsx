import type { Pokemon } from "../lib/types";
import styles from "./Pocket.module.css";

type Props = {
  pokemon: Pokemon | null;
  index: number;
};

const ARTWORK = (dex: number) =>
  `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/${dex}.png`;

export function Pocket({ pokemon, index }: Props) {
  if (pokemon === null) {
    return <div className={`${styles.pocket} ${styles.blank}`} aria-hidden="true" />;
  }

  const conseguido = pokemon.wishlist_count > 0;

  return (
    <article
      className={styles.pocket}
      style={{ "--delay": `${index * 20}ms` } as React.CSSProperties}
    >
      <span className={styles.dex}>{String(pokemon.dex_number).padStart(3, "0")}</span>

      <div className={styles.art}>
        <img src={ARTWORK(pokemon.dex_number)} alt="" loading="lazy" />
      </div>

      <div className={styles.plate}>
        <h2 className={styles.name}>{pokemon.name}</h2>
        <span
          className={conseguido ? styles.lightOn : styles.lightOff}
          aria-label={conseguido ? "con rutas de caza" : "sin rutas"}
        />
      </div>

      <span className={styles.sheen} aria-hidden="true" />
    </article>
  );
}
