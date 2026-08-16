import Link from "next/link";
import styles from "./Ficha.module.css";

export default function PokemonNoEncontrado() {
  return (
    <main className={styles.pantalla}>
      <div className={styles.noEncontrado}>
        <h1>No encontramos ese Pokémon</h1>
        <p>El número no existe en los 151 originales.</p>
        <Link href="/" className={styles.volver}>
          ‹ Volver al binder
        </Link>
      </div>
    </main>
  );
}
