import Link from "next/link";
import type { OtraCarta } from "../lib/types";
import pocketStyles from "../binder/Pocket.module.css";
import styles from "./Otras.module.css";

type Props = {
  cartas: OtraCarta[];
};

function formatearPrecio(precio: number | null): string | null {
  return precio === null ? null : `$${precio.toFixed(2)}`;
}

export function Otras({ cartas }: Props) {
  return (
    <main className={styles.pantalla}>
      <Link href="/" className={styles.volver}>
        ‹ Volver al binder
      </Link>

      <header className={styles.cabecera}>
        <h1 className={styles.titulo}>Otras cartas</h1>
        <p className={styles.subtitulo}>
          {cartas.length === 0
            ? "Las últimas páginas del binder."
            : cartas.length === 1
              ? "1 carta que no es de los 151."
              : `${cartas.length} cartas que no son de los 151.`}
        </p>
      </header>

      {cartas.length === 0 ? (
        <div className={styles.vacia}>
          <p>
            Acá viven las cartas que no son de los 151: de otra generación, sin número de
            Pokédex en el catálogo, o sin identificar todavía.
          </p>
          <p>Cuando registres una, aparece en esta página.</p>
        </div>
      ) : (
        <div className={styles.grid}>
          {cartas.map((carta) => {
            const foto = carta.photo_url ?? carta.image_url;
            const precio = formatearPrecio(carta.purchase_price_usd);
            const detalle = [carta.set_name, carta.local_id].filter(Boolean).join(" · ");
            const nombre = carta.card_name ?? "Sin identificar";

            return (
              <div key={carta.id} className={pocketStyles.pocket}>
                <div className={pocketStyles.face}>
                  {foto ? (
                    <img className={pocketStyles.card} src={foto} alt="" loading="lazy" />
                  ) : (
                    <div className={pocketStyles.noCard}>
                      <span>Sin foto</span>
                    </div>
                  )}
                  <span className={pocketStyles.sheen} aria-hidden="true" />
                  <footer className={styles.plate}>
                    <span className={styles.nombre}>{nombre}</span>
                    {detalle && <span className={styles.detalle}>{detalle}</span>}
                    {precio && <span className={styles.precio}>{precio}</span>}
                  </footer>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
