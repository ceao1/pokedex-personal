import Link from "next/link";
import type { OwnedCopyDetail, PokemonDetail } from "../../lib/types";
import styles from "./Ficha.module.css";

const VARIANTE_TEXTOS: Record<string, string> = {
  normal: "Normal",
  reverse: "Reverse",
  holo: "Holo",
  first_edition: "1st Edition",
  shadowless: "Shadowless",
  unlimited: "Unlimited",
};

function textoVariante(label: string | null): string | null {
  if (!label) return null;
  return VARIANTE_TEXTOS[label] ?? label;
}

function formatearFecha(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("es", {
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(new Date(iso));
  } catch {
    return "—";
  }
}

function formatearPrecio(precio: number | null): string {
  return precio === null ? "—" : `$${precio.toFixed(2)}`;
}

type Props = {
  pokemon: PokemonDetail;
  copias: (OwnedCopyDetail & { arte_catalogo: string | null })[];
};

export function Ficha({ pokemon, copias }: Props) {
  const dex = String(pokemon.dex_number).padStart(3, "0");
  const params = new URLSearchParams({ dex: String(pokemon.dex_number), name: pokemon.name });

  const opcionesConPrecio = pokemon.options.filter((o) => o.price_usd !== null);
  const precioMinimo =
    opcionesConPrecio.length > 0 ? Math.min(...opcionesConPrecio.map((o) => o.price_usd as number)) : null;

  return (
    <main className={styles.pantalla}>
      <Link href="/" className={styles.volver}>
        ‹ Volver al binder
      </Link>

      <header className={styles.cabecera}>
        <p className={styles.dex}>{dex}</p>
        <h1 className={styles.nombre}>{pokemon.name}</h1>
        <p className={styles.resumen}>
          {pokemon.owned_count === 0
            ? "Todavía no tienes ninguno."
            : pokemon.owned_count === 1
              ? "Tienes 1 ejemplar."
              : `Tienes ${pokemon.owned_count} ejemplares.`}
        </p>
      </header>

      <section className={styles.seccion}>
        <h2 className={styles.tituloSeccion}>Tus ejemplares</h2>

        {copias.length === 0 ? (
          <div className={styles.vacio}>
            <p>Todavía no registraste ningún ejemplar de {pokemon.name}.</p>
            <Link href={`/registrar?${params.toString()}`} className={styles.botonPrimario}>
              Registrar un ejemplar
            </Link>
          </div>
        ) : (
          <ul className={styles.listaEjemplares}>
            {copias.map((copia) => {
              const foto = copia.photo_url ?? copia.arte_catalogo;
              const esFotoPropia = copia.photo_url !== null;
              return (
                <li key={copia.id} className={styles.ejemplar}>
                  <div className={styles.ejemplarFoto}>
                    {foto ? (
                      <img src={foto} alt="" loading="lazy" />
                    ) : (
                      <span className={styles.sinArte} aria-hidden="true" />
                    )}
                    {!esFotoPropia && foto && (
                      <span className={styles.etiquetaArte}>Arte del catálogo</span>
                    )}
                  </div>
                  <div className={styles.ejemplarDatos}>
                    <p className={styles.ejemplarNombre}>{copia.card_name ?? pokemon.name}</p>
                    <p className={styles.ejemplarDetalle}>
                      {copia.set_name ?? "Set desconocido"}
                      {copia.local_id ? ` · ${copia.local_id}` : ""}
                      {textoVariante(copia.variant_label) ? ` · ${textoVariante(copia.variant_label)}` : ""}
                    </p>
                    <p className={styles.ejemplarDetalle}>
                      {copia.condition ? `Condición: ${copia.condition}` : "Condición: sin registrar"}
                      {" · "}
                      Pagado: {formatearPrecio(copia.purchase_price_usd)}
                    </p>
                    <p className={styles.ejemplarFecha}>
                      Registrado el {formatearFecha(copia.created_at)}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        {copias.length > 0 && (
          <Link href={`/registrar?${params.toString()}`} className={styles.botonSecundario}>
            Registrar otro ejemplar
          </Link>
        )}
      </section>

      <section className={styles.seccion}>
        <h2 className={styles.tituloSeccion}>Rutas de caza</h2>

        {pokemon.options.length === 0 ? (
          <p className={styles.hint}>Todavía no hay rutas registradas para {pokemon.name}.</p>
        ) : (
          <ul className={styles.listaRutas}>
            {pokemon.options.map((opcion) => {
              const esLaMasBarata = precioMinimo !== null && opcion.price_usd === precioMinimo;
              return (
                <li key={opcion.id} className={styles.ruta}>
                  <div className={styles.rutaFoto}>
                    {opcion.image_url ? (
                      <img src={opcion.image_url} alt="" loading="lazy" />
                    ) : (
                      <span className={styles.sinArte} aria-hidden="true" />
                    )}
                  </div>
                  <div className={styles.rutaDatos}>
                    <p className={styles.rutaNombre}>
                      {opcion.card_name ?? opcion.raw_text}
                      {esLaMasBarata && <span className={styles.masBarata}>Más barata</span>}
                    </p>
                    <p className={styles.ejemplarDetalle}>{opcion.set_name ?? "Set desconocido"}</p>
                    <p className={styles.rutaPrecio}>{formatearPrecio(opcion.price_usd)}</p>
                    <p className={styles.ejemplarFecha}>
                      Precio congelado el {formatearFecha(opcion.price_captured_at)}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </main>
  );
}
