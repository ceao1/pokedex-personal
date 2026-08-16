import Link from "next/link";
import { Compra } from "./Compra";
import styles from "./Compra.module.css";

export const metadata = {
  title: "Registrar un lote — Pokédex viviente",
};

export default function NuevaCompraPage() {
  return (
    <main className={styles.pantalla}>
      <header className={styles.encabezado}>
        <Link href="/" className={styles.volver}>
          ‹ Binder
        </Link>
        <h1 className={styles.titulo}>Registrar un sobre o un lote</h1>
        <p className={styles.hintCabecera}>
          Un solo precio, varias fotos, varias cartas por foto.
        </p>
      </header>
      <Compra />
    </main>
  );
}
