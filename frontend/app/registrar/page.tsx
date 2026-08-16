import Link from "next/link";
import { Captura } from "./Captura";
import styles from "./Captura.module.css";

export const metadata = {
  title: "Registrar una carta — Pokédex viviente",
};

type SearchParams = { dex?: string; name?: string };

export default async function RegistrarPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { dex, name } = await searchParams;

  return (
    <main className={styles.pantalla}>
      <header className={styles.encabezado}>
        <Link href="/" className={styles.volver}>
          ‹ Binder
        </Link>
        <h1 className={styles.titulo}>
          {name ? `Registrar un ejemplar de ${name}` : "Registrar una carta"}
        </h1>
        {dex && (
          <p className={styles.hintCabecera}>
            Número {String(dex).padStart(3, "0")} del Pokédex.
          </p>
        )}
      </header>
      <Captura />
    </main>
  );
}
