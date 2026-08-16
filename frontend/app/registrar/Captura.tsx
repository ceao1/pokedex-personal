"use client";

import { useEffect, useRef, useState } from "react";
import {
  actualizarCaptura,
  buscarCarta,
  crearCaptura,
  identificarCaptura,
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
import { redimensionar } from "../lib/imagen";
import type { Card, Identificacion, StartCapture, Variant, VariantLabel } from "../lib/types";
import { CHIPS_MODERNOS, CHIPS_VINTAGE, SETS_WOTC, elegirVariante } from "../lib/variantes";
import styles from "./Captura.module.css";

const SET_RECORDADO = "registrar:ultimo-set";

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

  // La identificación por foto propone; nunca escribe los campos por su
  // cuenta (ver `aceptarIdentificacion`). `null` cubre tres casos que no
  // hace falta distinguir en la pantalla: todavía no llegó, la llave no
  // está configurada, o la llamada falló -- en los tres el registro a
  // mano sigue exactamente igual.
  const [identificacion, setIdentificacion] = useState<Identificacion | null>(null);
  const [identificando, setIdentificando] = useState(false);

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

  /** Se dispara sola en cuanto la foto queda confirmada, en segundo plano.
   * Nunca bloquea el registro a mano: si el dueño ya terminó de escribir el
   * número mientras esto corría, lo suyo gana (ver `aceptarIdentificacion`,
   * que solo actúa si el dueño toca el botón). */
  async function dispararIdentificacion(clientDraftId: string) {
    setIdentificando(true);
    try {
      const resultado = await identificarCaptura(clientDraftId);
      // La respuesta puede llegar después de que el dueño ya haya empezado
      // a registrar otra carta: si el borrador actual ya no es este, la
      // propuesta es de una foto que ya no está en pantalla.
      if (clientDraftIdRef.current === clientDraftId) {
        setIdentificacion(resultado);
      }
    } finally {
      if (clientDraftIdRef.current === clientDraftId) {
        setIdentificando(false);
      }
    }
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
      void dispararIdentificacion(clientDraftId);
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
    setIdentificacion(null);
    setIdentificando(false);
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

  /** Único punto donde la propuesta de la foto llega a los campos: un clic
   * del dueño. Nunca ocurre sola, aunque haya llegado antes de que él
   * escribiera nada -- aceptar es un acto suyo, no un efecto de la subida. */
  function aceptarIdentificacion() {
    const propuesta = identificacion?.carta;
    if (!propuesta) return;
    setSetId(propuesta.set_id);
    setNumero(
      propuesta.set_card_count ? `${propuesta.local_id}/${propuesta.set_card_count}` : propuesta.local_id
    );
    setCarta(propuesta);
    setVarianteLabel(null);
    setVarianteResuelta(null);
  }

  /** Cuando el modelo leyó el número pero no pudo resolver la carta contra
   * el catálogo (set no identificado, número inexistente, confianza baja):
   * el número leído igual sirve de punto de partida para que el dueño
   * complete el set a mano, en vez de tirar todo lo que sí se leyó.
   *
   * A propósito también borra el set: si quedara el que recuerda
   * `localStorage` de una carta anterior, la búsqueda automática por
   * set+número podría "resolver" contra una carta real pero equivocada,
   * sin que el dueño la haya confirmado -- exactamente la inercia que la
   * identificación no puede permitirse. */
  function usarNumeroLeido() {
    const numeroLeido = identificacion?.reconocido?.number;
    if (!numeroLeido) return;
    setSetId("");
    setNumero(numeroLeido);
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
    setIdentificacion(null);
    setIdentificando(false);
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

  // Una carta resuelta cuyo dex_number no cae en 1..151 no es del proyecto:
  // vivirá en "Otras cartas", nunca en el binder. Se avisa, no se bloquea
  // (spec: "avisar antes"), y el aviso nombra la carta concreta.
  const fueraDelProyecto =
    carta !== null && (carta.dex_number === null || carta.dex_number < 1 || carta.dex_number > 151);

  // Cuando la identificación por foto corrió y no resolvió ninguna carta, y
  // el dueño tampoco la precisó a mano todavía, no hay forma de saber si es
  // de los 151 -- el mismo aviso, honesto sobre la incertidumbre.
  const sinIdentificar = carta === null && identificacion !== null && !identificacion.carta;

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

      {identificando && (
        <p className={styles.identificando} aria-live="polite">
          Analizando la foto…
        </p>
      )}

      {identificacion?.carta && (
        <div className={styles.propuesta}>
          {identificacion.carta.image_url && (
            <img
              className={styles.propuestaImagen}
              src={identificacion.carta.image_url}
              alt=""
              loading="lazy"
            />
          )}
          <div className={styles.propuestaDatos}>
            <p className={styles.propuestaEtiqueta}>
              Reconocida por la foto — confirma que es esta
            </p>
            <p className={styles.propuestaNombre}>{identificacion.carta.name}</p>
            <p className={styles.propuestaDetalle}>
              {identificacion.carta.set_name} · {identificacion.carta.local_id}
              {identificacion.carta.set_card_count ? `/${identificacion.carta.set_card_count}` : ""}
            </p>
            <button type="button" className={styles.propuestaBoton} onClick={aceptarIdentificacion}>
              Usar esta carta
            </button>
          </div>
        </div>
      )}

      {identificacion && !identificacion.carta && (
        <div className={styles.propuestaFallida}>
          <p>{identificacion.motivo || "No pude leer el número. Escríbelo tú."}</p>
          {/* Aunque no se resolvió contra el catálogo, lo que sí se leyó
              sirve: "no supo cuál Pokémon era" es justo la queja que esto
              responde, aun sin número o set confirmados. */}
          {(identificacion.reconocido?.species ||
            identificacion.reconocido?.name ||
            identificacion.reconocido?.number) && (
            <p className={styles.hint}>
              Se leyó
              {identificacion.reconocido?.species ? ` ${identificacion.reconocido.species}` : ""}
              {identificacion.reconocido?.dex_number != null
                ? ` (número ${String(identificacion.reconocido.dex_number).padStart(3, "0")} del Pokédex)`
                : ""}
              {identificacion.reconocido?.name &&
              identificacion.reconocido.name !== identificacion.reconocido?.species
                ? ` — ${identificacion.reconocido.name}`
                : ""}
              {identificacion.reconocido?.number
                ? `, número de colección ${identificacion.reconocido.number}`
                : ""}
              .
            </p>
          )}
          {identificacion.reconocido?.number && (
            <button
              type="button"
              className={styles.propuestaBotonSecundario}
              onClick={usarNumeroLeido}
            >
              Usar este número
            </button>
          )}
        </div>
      )}

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

      {fueraDelProyecto && (
        <p className={styles.aviso} aria-live="polite">
          <strong>{carta?.name} no es de los 151.</strong> Se guardará en <em>Otras cartas</em>,
          no en el binder.
        </p>
      )}

      {sinIdentificar && (
        <p className={styles.aviso} aria-live="polite">
          Sin identificar la carta no sabemos si es de los 151. Se guardará en{" "}
          <em>Otras cartas</em> hasta que la precises.
        </p>
      )}

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
