import Link from "next/link";
import { Captura } from "./Captura";
import styles from "./Captura.module.css";

export const metadata = {
  title: "Registrar una carta — Pokédex viviente",
};

export default function RegistrarPage() {
  return (
    <main className={styles.pantalla}>
      <header className={styles.encabezado}>
        <Link href="/" className={styles.volver}>
          ‹ Binder
        </Link>
        <h1 className={styles.titulo}>Registrar una carta</h1>
      </header>
      <Captura />
    </main>
  );
}
