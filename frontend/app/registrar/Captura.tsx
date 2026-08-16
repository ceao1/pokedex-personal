"use client";

import { useEffect, useRef, useState } from "react";
import {
  actualizarCaptura,
  buscarCarta,
  crearCaptura,
  marcarFotoSubida,
  nuevoClientDraftId,
  subirFoto,
} from "../lib/api";
import {
  eliminarFotoPendiente,
  guardarFotoPendiente,
  listarFotosPendientes,
  type FotoPendiente,
} from "../lib/fotosPendientes";
import type { Card, StartCapture, Variant, VariantLabel } from "../lib/types";
import styles from "./Captura.module.css";

// Los sets vintage (1999-2003) son los únicos con chips "1st Edition",
// "Shadowless" y "Unlimited" (spec §6.2). Todo lo demás es moderno.
const SETS_WOTC = new Set(["base1", "base2", "base3", "basep"]);

const CHIPS_MODERNOS: { label: VariantLabel; texto: string }[] = [
  { label: "normal", texto: "Normal" },
  { label: "reverse", texto: "Reverse" },
  { label: "holo", texto: "Holo" },
];

const CHIPS_VINTAGE: { label: VariantLabel; texto: string }[] = [
  { label: "first_edition", texto: "1st Edition" },
  { label: "shadowless", texto: "Shadowless" },
  { label: "unlimited", texto: "Unlimited" },
];

const SET_RECORDADO = "registrar:ultimo-set";

/** Paso 1 del mapeo de chip a variante (spec §6.2): qué fila de
 * `card_variant` corresponde al chip que tocó el usuario. */
function coincideVariante(variante: Variant, label: VariantLabel): boolean {
  switch (label) {
    case "normal":
      return variante.type === "normal";
    case "reverse":
      return variante.type === "reverse";
    case "holo":
      return variante.type === "holo" && variante.subtype === null;
    case "first_edition":
      return variante.stamp.includes("1st-edition");
    case "shadowless":
      return variante.subtype === "shadowless" && !variante.stamp.includes("1st-edition");
    case "unlimited":
      return variante.subtype === "unlimited";
    default:
      return false;
  }
}

/** Paso 2: si quedó más de una fila candidata, gana la menos exótica.
 * `VariantOut` no trae `size` (a diferencia de `variants.py` en el
 * backend), pero `stamp` + `foil` ya alcanzan para el caso que importa:
 * Bulbasaur sv03.5-001 tiene dos entradas `normal` y la que lleva
 * `stamp: ["set-logo"]` cuesta 280 veces más que la común. */
function especificidad(variante: Variant): [number, number] {
  return [variante.stamp.length > 0 ? 1 : 0, variante.foil ? 1 : 0];
}

function elegirVariante(variantes: Variant[], label: VariantLabel): Variant | null {
  const candidatas = variantes.filter((v) => coincideVariante(v, label));
  if (candidatas.length === 0) return null;
  return candidatas.reduce((mejor, actual) => {
    const [s1, f1] = especificidad(mejor);
    const [s2, f2] = especificidad(actual);
    if (s2 < s1) return actual;
    if (s2 === s1 && f2 < f1) return actual;
    return mejor;
  });
}

async function redimensionar(archivo: File, ladoMayor: number, calidad = 0.85): Promise<Blob> {
  const bitmap = await createImageBitmap(archivo);
  try {
    const escala = Math.min(1, ladoMayor / Math.max(bitmap.width, bitmap.height));
    const ancho = Math.max(1, Math.round(bitmap.width * escala));
    const alto = Math.max(1, Math.round(bitmap.height * escala));
    const canvas = document.createElement("canvas");
    canvas.width = ancho;
    canvas.height = alto;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Este navegador no puede procesar imágenes.");
    ctx.drawImage(bitmap, 0, 0, ancho, alto);
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error("No se pudo generar la imagen."))),
        "image/jpeg",
        calidad
      );
    });
  } finally {
    bitmap.close();
  }
}

type EstadoSubida = "sin_foto" | "subiendo" | "lista" | "error";

type FotosRedimensionadas = { front: Blob; thumb: Blob };

export function Captura() {
  const draftRef = useRef<StartCapture | null>(null);
  const clientDraftIdRef = useRef<string | null>(null);
  const fotosRef = useRef<FotosRedimensionadas | null>(null);
  const fotoMarcadaRef = useRef(false);
  // Bytes que ya aterrizaron en el bucket, aunque `marcarFotoSubida` no
  // haya confirmado todavía -- distinto de `fotoMarcadaRef`, que es la
  // confirmación del backend. Sin este ref, un fallo de
  // `marcarFotoSubida` tras una subida exitosa deja los bytes sin fila
  // que los referencie y sin forma de recuperarlos desde `guardar()`.
  const bytesSubidosRef = useRef(false);

  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [estadoFoto, setEstadoFoto] = useState<EstadoSubida>("sin_foto");

  const [pendientes, setPendientes] = useState<FotoPendiente[]>([]);
  const [reanudando, setReanudando] = useState(false);
  const [errorReanudar, setErrorReanudar] = useState<string | null>(null);

  const [setId, setSetId] = useState("sv03.5");
  const [numero, setNumero] = useState("");
  const [carta, setCarta] = useState<Card | null>(null);
  const [buscandoCarta, setBuscandoCarta] = useState(false);
  const [errorCarta, setErrorCarta] = useState<string | null>(null);

  const [varianteLabel, setVarianteLabel] = useState<VariantLabel | null>(null);
  const [varianteResuelta, setVarianteResuelta] = useState<Variant | null>(null);

  const [precio, setPrecio] = useState("");

  const [guardando, setGuardando] = useState(false);
  const [guardado, setGuardado] = useState(false);
  const [errorGuardado, setErrorGuardado] = useState<string | null>(null);

  useEffect(() => {
    const recordado = window.localStorage.getItem(SET_RECORDADO);
    if (recordado) setSetId(recordado);
  }, []);

  useEffect(() => {
    if (setId.trim()) {
      window.localStorage.setItem(SET_RECORDADO, setId.trim());
    }
  }, [setId]);

  // Al escribir el número se consulta el catálogo (debounce de 400ms): es
  // la identificación manual, rápida y exacta, sin API de visión.
  useEffect(() => {
    const localId = numero.split("/")[0].trim();
    if (!setId.trim() || !localId) {
      setCarta(null);
      setErrorCarta(null);
      setBuscandoCarta(false);
      return;
    }
    setBuscandoCarta(true);
    setErrorCarta(null);
    let vigente = true;
    const timeout = setTimeout(() => {
      buscarCarta(setId.trim(), localId)
        .then((encontrada) => {
          if (!vigente) return;
          setCarta(encontrada);
          setVarianteLabel(null);
          setVarianteResuelta(null);
        })
        .catch(() => {
          if (!vigente) return;
          setCarta(null);
          setVarianteLabel(null);
          setVarianteResuelta(null);
          setErrorCarta(
            `No encontramos el número ${localId} en el set ${setId.trim()}. Revisa el set y el número.`
          );
        })
        .finally(() => {
          if (vigente) setBuscandoCarta(false);
        });
    }, 400);
    return () => {
      vigente = false;
      clearTimeout(timeout);
    };
  }, [setId, numero]);

  // Refresca el banner de "fotos pendientes de una sesión anterior": al
  // montar, y de nuevo cada vez que el borrador actual cambia (guardar,
  // registrar otra), para no dejar una foto de una carta anterior
  // escondida sin más que el silencio.
  async function refrescarPendientes() {
    try {
      const todas = await listarFotosPendientes();
      setPendientes(todas.filter((p) => p.clientDraftId !== clientDraftIdRef.current));
    } catch {
      // Best-effort: si IndexedDB falla acá no hay nada más que mostrar,
      // pero tampoco debe romper la pantalla.
    }
  }

  useEffect(() => {
    void refrescarPendientes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function idBorrador(): string {
    if (!clientDraftIdRef.current) {
      clientDraftIdRef.current = nuevoClientDraftId();
    }
    return clientDraftIdRef.current;
  }

  async function asegurarBorrador(): Promise<StartCapture> {
    if (draftRef.current) return draftRef.current;
    const inicio = await crearCaptura(idBorrador());
    draftRef.current = inicio;
    return inicio;
  }

  /** Sube las dos renditions ya redimensionadas y marca la foto en el
   * backend. Una URL firmada vacía significa "ya subido, no hace falta
   * volver a mandar la foto" (ver `_firmar_subida_o_ya_existente` en el
   * backend) -- mandarla igual haría un PUT contra la URL de la propia
   * página. */
  async function subirAmbasFotos(
    clientDraftId: string,
    uploads: StartCapture["uploads"],
    front: Blob,
    thumb: Blob
  ) {
    setEstadoFoto("subiendo");
    try {
      await Promise.all([
        uploads.front ? subirFoto(uploads.front, front) : Promise.resolve(),
        uploads.thumb ? subirFoto(uploads.thumb, thumb) : Promise.resolve(),
      ]);
      bytesSubidosRef.current = true;
      await marcarFotoSubida(clientDraftId);
      fotoMarcadaRef.current = true;
      await eliminarFotoPendiente(clientDraftId);
      setEstadoFoto("lista");
    } catch {
      // Nunca se pierde la foto por un fallo de red: los blobs ya están en
      // IndexedDB desde antes de este intento, y el ejemplar puede
      // guardarse igual sin foto confirmada todavía. La pantalla lo deja
      // claro y ofrece reintentar.
      setEstadoFoto("error");
    }
  }

  async function onFotoElegida(event: React.ChangeEvent<HTMLInputElement>) {
    const archivo = event.target.files?.[0];
    if (!archivo) return;
    setPreviewUrl(URL.createObjectURL(archivo));
    fotoMarcadaRef.current = false;
    bytesSubidosRef.current = false;
    setEstadoFoto("subiendo");
    try {
      const [front, thumb] = await Promise.all([
        redimensionar(archivo, 2048),
        redimensionar(archivo, 400),
      ]);
      const clientDraftId = idBorrador();
      // Paso 1 de la spec (§6): los blobs quedan en IndexedDB *antes* de
      // la primera llamada de red. Si la subida falla, la pestaña se
      // recarga o iOS mata la PWA en segundo plano, la foto sigue en el
      // dispositivo.
      await guardarFotoPendiente(clientDraftId, front, thumb);
      fotosRef.current = { front, thumb };
      const inicio = await asegurarBorrador();
      await subirAmbasFotos(clientDraftId, inicio.uploads, front, thumb);
    } catch {
      setEstadoFoto("error");
    }
  }

  async function reintentarFoto() {
    const clientDraftId = clientDraftIdRef.current;
    const fotos = fotosRef.current;
    if (!clientDraftId || !fotos) return;
    setEstadoFoto("subiendo");
    try {
      // Las URLs firmadas son de un solo uso: si algún byte ya llegó al
      // bucket, reintentar el mismo PUT devuelve 409 Duplicate. Pedir
      // firmas nuevas es seguro porque `POST /captures` es idempotente
      // por `client_draft_id`.
      const inicio = await crearCaptura(clientDraftId);
      draftRef.current = inicio;
      await subirAmbasFotos(clientDraftId, inicio.uploads, fotos.front, fotos.thumb);
    } catch {
      setEstadoFoto("error");
    }
  }

  async function reanudarPendientes() {
    setReanudando(true);
    setErrorReanudar(null);
    const restantes: FotoPendiente[] = [];
    for (const pendiente of pendientes) {
      try {
        const inicio = await crearCaptura(pendiente.clientDraftId);
        await Promise.all([
          inicio.uploads.front
            ? subirFoto(inicio.uploads.front, pendiente.front)
            : Promise.resolve(),
          inicio.uploads.thumb
            ? subirFoto(inicio.uploads.thumb, pendiente.thumb)
            : Promise.resolve(),
        ]);
        await marcarFotoSubida(pendiente.clientDraftId);
        await eliminarFotoPendiente(pendiente.clientDraftId);
      } catch {
        restantes.push(pendiente);
      }
    }
    setPendientes(restantes);
    setReanudando(false);
    if (restantes.length > 0) {
      setErrorReanudar(
        `No se pudieron subir ${restantes.length} ${restantes.length === 1 ? "foto" : "fotos"}. Revisa tu conexión e inténtalo de nuevo.`
      );
    }
  }

  function seleccionarVariante(label: VariantLabel) {
    setVarianteLabel(label);
    setVarianteResuelta(carta ? elegirVariante(carta.variants, label) : null);
  }

  async function guardar() {
    setGuardando(true);
    setErrorGuardado(null);
    try {
      const draft = await asegurarBorrador();
      // No depende de `estadoFoto === "lista"`: si las dos renditions ya
      // llegaron al bucket pero `marcarFotoSubida` falló después (ver
      // finding), los bytes existen igual y hay que intentar marcarlos
      // acá también, o quedan huérfanos para siempre.
      if (bytesSubidosRef.current && !fotoMarcadaRef.current) {
        try {
          await marcarFotoSubida(draft.client_draft_id);
          fotoMarcadaRef.current = true;
          await eliminarFotoPendiente(draft.client_draft_id);
          setEstadoFoto("lista");
        } catch {
          // Los bytes ya están en el bucket; si marcar vuelve a fallar el
          // ejemplar se guarda igual y la foto queda en el banner de
          // pendientes para reintentar más tarde.
        }
      }
      await actualizarCaptura(draft.client_draft_id, {
        card_id: carta?.id ?? null,
        variant_id: varianteResuelta?.id ?? null,
        variant_label: varianteLabel,
        purchase_price_usd: precio.trim() === "" ? null : precio.trim(),
        capture_status: "listo",
      });
      setGuardado(true);
      void refrescarPendientes();
    } catch {
      setErrorGuardado("No se pudo guardar el ejemplar. Revisa tu conexión e intenta de nuevo.");
    } finally {
      setGuardando(false);
    }
  }

  function registrarOtra() {
    draftRef.current = null;
    clientDraftIdRef.current = null;
    fotosRef.current = null;
    fotoMarcadaRef.current = false;
    bytesSubidosRef.current = false;
    setPreviewUrl(null);
    setEstadoFoto("sin_foto");
    setNumero("");
    setCarta(null);
    setErrorCarta(null);
    setVarianteLabel(null);
    setVarianteResuelta(null);
    setPrecio("");
    setGuardado(false);
    setErrorGuardado(null);
    void refrescarPendientes();
  }

  const esSetWotc = carta !== null && SETS_WOTC.has(carta.set_id);
  const puedeGuardar = carta !== null && !guardando;

  if (guardado) {
    return (
      <div className={styles.tarjeta}>
        <p className={styles.exito}>
          {carta?.name ?? "La carta"} quedó registrada
          {estadoFoto === "error"
            ? ". La foto se guardó en este dispositivo, pero todavía no se subió."
            : "."}
        </p>
        {estadoFoto === "error" && (
          <p className={styles.estadoFoto}>
            <button type="button" className={styles.reintentar} onClick={reintentarFoto}>
              Reintentar subir la foto
            </button>
          </p>
        )}
        <div className={styles.accionesFinales}>
          <a className={styles.botonPrimario} href="/">
            Ir al binder
          </a>
          <button type="button" className={styles.botonSecundario} onClick={registrarOtra}>
            Registrar otra
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.tarjeta}>
      {pendientes.length > 0 && (
        <div className={styles.pendientes}>
          <p>
            Tienes {pendientes.length} {pendientes.length === 1 ? "foto" : "fotos"} pendiente
            {pendientes.length === 1 ? "" : "s"} de subir de una sesión anterior.
          </p>
          {errorReanudar && <p className={styles.error}>{errorReanudar}</p>}
          <button
            type="button"
            className={styles.pendientesBoton}
            onClick={reanudarPendientes}
            disabled={reanudando}
          >
            {reanudando ? "Subiendo…" : "Reanudar subida"}
          </button>
        </div>
      )}

      <label className={styles.camara}>
        <input
          type="file"
          accept="image/*"
          capture="environment"
          onChange={onFotoElegida}
          className={styles.inputOculto}
        />
        {previewUrl ? (
          <img src={previewUrl} alt="Foto de la carta que estás registrando" className={styles.preview} />
        ) : (
          <span className={styles.camaraTexto}>Fotografiar la carta</span>
        )}
      </label>

      <p className={styles.estadoFoto} aria-live="polite">
        {estadoFoto === "sin_foto" && "Sin foto todavía — puedes guardar sin ella."}
        {estadoFoto === "subiendo" && "Subiendo foto…"}
        {estadoFoto === "lista" && "Foto guardada."}
        {estadoFoto === "error" && (
          <>
            No se pudo subir la foto todavía. Queda guardada en este dispositivo — puedes
            reintentar cuando quieras.{" "}
            <button type="button" className={styles.reintentar} onClick={reintentarFoto}>
              Reintentar
            </button>
          </>
        )}
      </p>

      <div className={styles.fila}>
        <label className={styles.campo}>
          <span>Set</span>
          <input
            type="text"
            value={setId}
            onChange={(e) => setSetId(e.target.value)}
            placeholder="sv03.5"
            autoCapitalize="none"
            autoCorrect="off"
          />
        </label>
        <label className={styles.campo}>
          <span>Número</span>
          <input
            type="text"
            inputMode="numeric"
            value={numero}
            onChange={(e) => setNumero(e.target.value)}
            placeholder="001/165"
          />
        </label>
      </div>

      {buscandoCarta && <p className={styles.hint}>Buscando la carta…</p>}
      {errorCarta && <p className={styles.error}>{errorCarta}</p>}

      {carta && (
        <div className={styles.cartaEncontrada}>
          {carta.image_url && (
            <img className={styles.cartaImagen} src={carta.image_url} alt="" loading="lazy" />
          )}
          <div>
            <p className={styles.cartaNombre}>{carta.name}</p>
            <p className={styles.cartaDetalle}>
              {carta.set_name} · {carta.local_id}
              {carta.set_card_count ? `/${carta.set_card_count}` : ""}
            </p>
          </div>
        </div>
      )}

      {carta && (
        <div className={styles.chips}>
          <div className={styles.grupoChips}>
            {CHIPS_MODERNOS.map(({ label, texto }) => (
              <button
                key={label}
                type="button"
                className={`${styles.chip} ${varianteLabel === label ? styles.chipActivo : ""}`}
                aria-pressed={varianteLabel === label}
                onClick={() => seleccionarVariante(label)}
              >
                {texto}
              </button>
            ))}
          </div>
          {esSetWotc && (
            <div className={styles.grupoChips}>
              {CHIPS_VINTAGE.map(({ label, texto }) => (
                <button
                  key={label}
                  type="button"
                  className={`${styles.chip} ${varianteLabel === label ? styles.chipActivo : ""}`}
                  aria-pressed={varianteLabel === label}
                  onClick={() => seleccionarVariante(label)}
                >
                  {texto}
                </button>
              ))}
            </div>
          )}
          {varianteLabel && (
            <p className={styles.hint}>
              {varianteResuelta?.price_usd != null
                ? `Precio de referencia: $${varianteResuelta.price_usd.toFixed(2)} USD`
                : "Sin precio de referencia para esta variante."}
            </p>
          )}
        </div>
      )}

      <label className={styles.campo}>
        <span>Precio pagado (USD)</span>
        <input
          type="number"
          inputMode="decimal"
          min="0"
          step="0.01"
          value={precio}
          onChange={(e) => setPrecio(e.target.value)}
          placeholder="0.00"
        />
      </label>

      {errorGuardado && <p className={styles.error}>{errorGuardado}</p>}

      <button
        type="button"
        className={styles.botonGuardar}
        disabled={!puedeGuardar}
        onClick={guardar}
      >
        {guardando ? "Guardando…" : "Guardar"}
      </button>
    </div>
  );
}
