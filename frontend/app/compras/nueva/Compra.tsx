"use client";

import { useMemo, useState } from "react";
import {
  agregarRelleno,
  buscarCarta,
  crearCompra,
  confirmarEjemplares,
  repartirCompra,
  subirTanda,
} from "../../lib/api";
import { redimensionar } from "../../lib/imagen";
import { CHIPS_MODERNOS, CHIPS_VINTAGE, SETS_WOTC, elegirVariante } from "../../lib/variantes";
import type {
  AllocationMethod,
  Card,
  PurchaseOut,
  PurchaseSourceType,
  Recognition,
  Variant,
  VariantLabel,
} from "../../lib/types";
import styles from "./Compra.module.css";

const LIMITE_RECOMENDADO = 12;

const FUENTES: { value: PurchaseSourceType; texto: string }[] = [
  { value: "sobre", texto: "Sobre" },
  { value: "lote", texto: "Lote" },
  { value: "tienda", texto: "Tienda" },
  { value: "online", texto: "Online" },
  { value: "intercambio", texto: "Intercambio" },
  { value: "regalo", texto: "Regalo" },
];

const METODOS: { value: AllocationMethod; texto: string }[] = [
  { value: "market_value", texto: "Valor de mercado" },
  { value: "equal", texto: "Partes iguales" },
  { value: "manual", texto: "Manual" },
];

let contador = 0;
function nuevaClave(): string {
  contador += 1;
  return `f${Date.now()}-${contador}`;
}

/** Una carta propuesta por una tanda, o agregada a mano, todavía sin
 * confirmar. `tanda` propone; `ejemplares` guarda -- esta fila vive solo en
 * el navegador hasta que el dueño la confirma (ver `guardarPendientes`). */
type FilaPropuesta = {
  key: string;
  origen: "tanda" | "manual";
  reconocido: Recognition | null;
  carta: Card | null;
  necesitaRevision: boolean;
  motivo: string;
  varianteLabel: VariantLabel | null;
  varianteResuelta: Variant | null;
  // Búsqueda inline para corregir o para resolver una lectura que no
  // encontró carta.
  setId: string;
  numero: string;
  buscando: boolean;
  errorBusqueda: string | null;
  corrigiendo: boolean;
};

function filaDesdeReconocido(reconocido: Recognition, carta: Card | null, necesitaRevision: boolean, motivo: string): FilaPropuesta {
  return {
    key: nuevaClave(),
    origen: "tanda",
    reconocido,
    carta,
    necesitaRevision,
    motivo,
    varianteLabel: null,
    varianteResuelta: null,
    setId: "",
    numero: reconocido.number ?? "",
    buscando: false,
    errorBusqueda: null,
    corrigiendo: false,
  };
}

/** Un ejemplar ya confirmado (guardado en `owned_copy`), con el nombre y el
 * arte que se mantienen en memoria desde el momento de confirmarlo --
 * `GET /compras/{id}` no los repite (ver `EjemplarDeCompraOut`). */
type EjemplarGuardado = {
  id: number;
  carta: Card | null;
  varianteLabel: VariantLabel | null;
  isBulk: boolean;
  costoUsd: number | null;
};

type AvisoTanda = {
  mensaje: string;
  requiereAtencion: boolean;
};

function esSetWotc(carta: Card | null): boolean {
  return carta !== null && SETS_WOTC.has(carta.set_id);
}

export function Compra() {
  // --- Cabecera: qué compraste y cuánto pagaste, una sola vez -------------
  const [sourceType, setSourceType] = useState<PurchaseSourceType | null>(null);
  const [totalUsd, setTotalUsd] = useState("");
  const [creandoCompra, setCreandoCompra] = useState(false);
  const [errorCompra, setErrorCompra] = useState<string | null>(null);
  const [compra, setCompra] = useState<PurchaseOut | null>(null);

  // --- Tandas ---------------------------------------------------------------
  const [cuantasHay, setCuantasHay] = useState("");
  const [tandaEnProceso, setTandaEnProceso] = useState(false);
  const [errorTanda, setErrorTanda] = useState<string | null>(null);
  const [avisoTanda, setAvisoTanda] = useState<AvisoTanda | null>(null);

  // --- Lista de confirmación --------------------------------------------------
  const [pendientes, setPendientes] = useState<FilaPropuesta[]>([]);
  const [guardandoEjemplares, setGuardandoEjemplares] = useState(false);
  const [errorGuardarEjemplares, setErrorGuardarEjemplares] = useState<string | null>(null);

  // Añadir una carta a mano.
  const [manualSetId, setManualSetId] = useState("sv03.5");
  const [manualNumero, setManualNumero] = useState("");
  const [buscandoManual, setBuscandoManual] = useState(false);
  const [errorManual, setErrorManual] = useState<string | null>(null);

  // --- Guardadas + relleno ----------------------------------------------------
  const [guardadas, setGuardadas] = useState<EjemplarGuardado[]>([]);
  const [rellenoCantidad, setRellenoCantidad] = useState("");
  const [guardandoRelleno, setGuardandoRelleno] = useState(false);
  const [errorRelleno, setErrorRelleno] = useState<string | null>(null);

  // --- Reparto ------------------------------------------------------------
  const [metodo, setMetodo] = useState<AllocationMethod>("market_value");
  const [costosManuales, setCostosManuales] = useState<Record<number, string>>({});
  const [repartiendo, setRepartiendo] = useState(false);
  const [errorReparto, setErrorReparto] = useState<string | null>(null);
  const [sumaAsignada, setSumaAsignada] = useState<number | null>(null);
  const [repartoAplicado, setRepartoAplicado] = useState(false);

  const puedeCrearCompra =
    sourceType !== null && totalUsd.trim() !== "" && !Number.isNaN(Number(totalUsd)) && !creandoCompra;

  async function onCrearCompra() {
    if (!sourceType) return;
    setCreandoCompra(true);
    setErrorCompra(null);
    try {
      const creada = await crearCompra(sourceType, totalUsd.trim());
      setCompra(creada);
    } catch {
      setErrorCompra("No se pudo crear la compra. Revisa tu conexión e intenta de nuevo.");
    } finally {
      setCreandoCompra(false);
    }
  }

  async function onFotoTanda(event: React.ChangeEvent<HTMLInputElement>) {
    const archivo = event.target.files?.[0];
    event.target.value = "";
    if (!archivo || !compra) return;
    setTandaEnProceso(true);
    setErrorTanda(null);
    const esperadasCrudo = cuantasHay.trim() ? Number(cuantasHay.trim()) : NaN;
    const esperadas = Number.isFinite(esperadasCrudo) && esperadasCrudo >= 1 ? esperadasCrudo : null;
    try {
      const foto = await redimensionar(archivo, 2048);
      const resultado = await subirTanda(compra.id, foto);
      const nuevasFilas = resultado.lecturas.map((lectura) =>
        filaDesdeReconocido(lectura.reconocido, lectura.carta, lectura.necesita_revision, lectura.motivo)
      );
      setPendientes((prev) => [...prev, ...nuevasFilas]);

      let mensaje: string;
      if (esperadas != null && resultado.total_encontradas < esperadas) {
        mensaje = `Encontré ${resultado.total_encontradas} de las ${esperadas} que dijiste. Toma otra foto o añade la que falta a mano.`;
      } else if (esperadas != null && resultado.total_encontradas > esperadas) {
        mensaje = `Encontré ${resultado.total_encontradas} cartas — más de las ${esperadas} que dijiste. Revisa la lista antes de guardar.`;
      } else if (esperadas != null) {
        mensaje = `Encontré las ${esperadas} cartas que dijiste.`;
      } else {
        mensaje =
          resultado.total_encontradas === 1
            ? "Encontré 1 carta en la foto. ¿Está completa?"
            : `Encontré ${resultado.total_encontradas} cartas en la foto. ¿Están todas?`;
      }
      if (resultado.excede_limite) {
        mensaje +=
          " Con más de doce cartas en una foto la lectura empieza a fallar en silencio: revisa el arte de cada una antes de guardar, o toma dos fotos en vez de una.";
      }
      setAvisoTanda({
        mensaje,
        requiereAtencion: true,
      });
      setCuantasHay("");
    } catch (error) {
      setErrorTanda(
        error instanceof Error
          ? error.message
          : "No se pudo leer la foto. Puedes registrar las cartas a mano."
      );
    } finally {
      setTandaEnProceso(false);
    }
  }

  function quitarFila(key: string) {
    setPendientes((prev) => prev.filter((f) => f.key !== key));
  }

  function seleccionarVarianteFila(key: string, label: VariantLabel) {
    setPendientes((prev) =>
      prev.map((f) =>
        f.key === key
          ? { ...f, varianteLabel: label, varianteResuelta: f.carta ? elegirVariante(f.carta.variants, label) : null }
          : f
      )
    );
  }

  function alternarCorregir(key: string) {
    setPendientes((prev) =>
      prev.map((f) => (f.key === key ? { ...f, corrigiendo: !f.corrigiendo, errorBusqueda: null } : f))
    );
  }

  function actualizarBusquedaFila(key: string, campo: "setId" | "numero", valor: string) {
    setPendientes((prev) => prev.map((f) => (f.key === key ? { ...f, [campo]: valor } : f)));
  }

  async function corregirFila(key: string) {
    const fila = pendientes.find((f) => f.key === key);
    if (!fila) return;
    const localId = fila.numero.split("/")[0].trim();
    if (!fila.setId.trim() || !localId) return;
    setPendientes((prev) => prev.map((f) => (f.key === key ? { ...f, buscando: true, errorBusqueda: null } : f)));
    try {
      const encontrada = await buscarCarta(fila.setId.trim(), localId);
      setPendientes((prev) =>
        prev.map((f) =>
          f.key === key
            ? {
                ...f,
                carta: encontrada,
                necesitaRevision: false,
                motivo: "",
                varianteLabel: null,
                varianteResuelta: null,
                corrigiendo: false,
                buscando: false,
              }
            : f
        )
      );
    } catch {
      setPendientes((prev) =>
        prev.map((f) =>
          f.key === key
            ? {
                ...f,
                buscando: false,
                errorBusqueda: `No encontramos el número ${localId} en el set ${fila.setId.trim()}.`,
              }
            : f
        )
      );
    }
  }

  async function agregarCartaManual() {
    const localId = manualNumero.split("/")[0].trim();
    if (!manualSetId.trim() || !localId) return;
    setBuscandoManual(true);
    setErrorManual(null);
    try {
      const encontrada = await buscarCarta(manualSetId.trim(), localId);
      const fila: FilaPropuesta = {
        key: nuevaClave(),
        origen: "manual",
        reconocido: null,
        carta: encontrada,
        necesitaRevision: false,
        motivo: "",
        varianteLabel: null,
        varianteResuelta: null,
        setId: manualSetId.trim(),
        numero: manualNumero,
        buscando: false,
        errorBusqueda: null,
        corrigiendo: false,
      };
      setPendientes((prev) => [...prev, fila]);
      setManualNumero("");
    } catch {
      setErrorManual(`No encontramos el número ${localId} en el set ${manualSetId.trim()}.`);
    } finally {
      setBuscandoManual(false);
    }
  }

  const filasListas = pendientes.filter((f) => f.carta && f.varianteResuelta);
  const puedeGuardarPendientes =
    compra !== null &&
    pendientes.length > 0 &&
    filasListas.length === pendientes.length &&
    !(avisoTanda?.requiereAtencion) &&
    !guardandoEjemplares;

  async function guardarPendientes() {
    if (!compra) return;
    setGuardandoEjemplares(true);
    setErrorGuardarEjemplares(null);
    try {
      const cuerpo = pendientes.map((f) => ({
        card_id: f.carta!.id,
        variant_id: f.varianteResuelta!.id,
        variant_label: f.varianteLabel,
      }));
      const { ids } = await confirmarEjemplares(compra.id, cuerpo);
      const nuevas: EjemplarGuardado[] = pendientes.map((f, i) => ({
        id: ids[i],
        carta: f.carta,
        varianteLabel: f.varianteLabel,
        isBulk: false,
        costoUsd: null,
      }));
      setGuardadas((prev) => [...prev, ...nuevas]);
      setPendientes([]);
      setRepartoAplicado(false);
    } catch {
      setErrorGuardarEjemplares("No se pudieron guardar las cartas. Revisa tu conexión e intenta de nuevo.");
    } finally {
      setGuardandoEjemplares(false);
    }
  }

  async function onAgregarRelleno() {
    const cantidad = Math.floor(Number(rellenoCantidad));
    if (!compra || !Number.isFinite(cantidad) || cantidad < 1) return;
    setGuardandoRelleno(true);
    setErrorRelleno(null);
    try {
      const { ids } = await agregarRelleno(compra.id, cantidad);
      setGuardadas((prev) => [
        ...prev,
        ...ids.map((id) => ({ id, carta: null, varianteLabel: null, isBulk: true, costoUsd: null })),
      ]);
      setRellenoCantidad("");
      setRepartoAplicado(false);
    } catch {
      setErrorRelleno("No se pudo añadir el relleno. Revisa tu conexión e intenta de nuevo.");
    } finally {
      setGuardandoRelleno(false);
    }
  }

  // Las bulk siempre reciben $0 y quedan fuera del reparto (`allocation.py`,
  // `_validar_manual` solo exige -- y solo suma -- el costo de las
  // elegibles): pedirle al dueño un número para ellas sería mentir sobre
  // qué compara la cuenta con el total.
  const guardadasElegibles = useMemo(() => guardadas.filter((g) => !g.isBulk), [guardadas]);
  const totalManualCentavos = useMemo(() => {
    return guardadasElegibles.reduce((acc, g) => {
      const valor = Number(costosManuales[g.id] ?? "0");
      return acc + Math.round((Number.isFinite(valor) ? valor : 0) * 100);
    }, 0);
  }, [guardadasElegibles, costosManuales]);
  const totalObjetivoCentavos = compra ? Math.round(compra.total_usd * 100) : 0;
  const manualCuadra = totalManualCentavos === totalObjetivoCentavos;

  async function aplicarReparto(m: AllocationMethod) {
    if (!compra) return;
    setMetodo(m);
    if (m === "manual" && !manualCuadra) return;
    setRepartiendo(true);
    setErrorReparto(null);
    try {
      const costos = m === "manual" ? costosManuales : undefined;
      const resultado = await repartirCompra(compra.id, m, costos);
      setGuardadas((prev) =>
        prev.map((g) => {
          const asign = resultado.asignaciones.find((a) => a.ejemplar_id === g.id);
          return asign ? { ...g, costoUsd: asign.costo_usd } : g;
        })
      );
      setSumaAsignada(resultado.asignaciones.reduce((acc, a) => acc + a.costo_usd, 0));
      setRepartoAplicado(true);
    } catch (error) {
      setErrorReparto(error instanceof Error ? error.message : "No se pudo repartir el costo.");
    } finally {
      setRepartiendo(false);
    }
  }

  return (
    <div className={styles.contenido}>
      {/* --- Cabecera: qué compraste y cuánto pagaste ------------------------- */}
      {!compra ? (
        <section className={styles.tarjeta}>
          <h2 className={styles.subtitulo}>¿Qué compraste?</h2>
          <div className={styles.grupoChips}>
            {FUENTES.map(({ value, texto }) => (
              <button
                key={value}
                type="button"
                className={`${styles.chip} ${sourceType === value ? styles.chipActivo : ""}`}
                aria-pressed={sourceType === value}
                onClick={() => setSourceType(value)}
              >
                {texto}
              </button>
            ))}
          </div>
          <label className={styles.campo}>
            <span>Cuánto pagaste en total (USD)</span>
            <input
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              value={totalUsd}
              onChange={(e) => setTotalUsd(e.target.value)}
              placeholder="0.00"
            />
          </label>
          {errorCompra && <p className={styles.error}>{errorCompra}</p>}
          <button
            type="button"
            className={styles.botonPrimario}
            disabled={!puedeCrearCompra}
            onClick={onCrearCompra}
          >
            {creandoCompra ? "Creando…" : "Empezar a registrar cartas"}
          </button>
        </section>
      ) : (
        <>
          <section className={styles.resumenCompra}>
            <span className={styles.resumenTipo}>
              {FUENTES.find((f) => f.value === compra.source_type)?.texto ?? compra.source_type}
            </span>
            <span className={styles.resumenTotal}>${compra.total_usd.toFixed(2)} USD</span>
          </section>

          {/* --- Tanda: fotografiar varias cartas a la vez ------------------------- */}
          <section className={styles.tarjeta}>
            <h2 className={styles.subtitulo}>Fotografiar una tanda</h2>
            <p className={styles.hint}>
              Extiende las cartas sobre una superficie plana, sin que se tapen, y dispara. Hasta
              doce por foto es lo medido sin error.
            </p>
            <label className={styles.campo}>
              <span>¿Cuántas cartas hay en la foto? (opcional)</span>
              <input
                type="number"
                inputMode="numeric"
                min="1"
                value={cuantasHay}
                onChange={(e) => setCuantasHay(e.target.value)}
                placeholder="12"
              />
            </label>
            <label className={styles.camara}>
              <input
                type="file"
                accept="image/*"
                capture="environment"
                onChange={onFotoTanda}
                className={styles.inputOculto}
                disabled={tandaEnProceso}
              />
              <span className={styles.camaraTexto}>
                {tandaEnProceso ? "Analizando la foto… puede tardar unos segundos." : "Fotografiar una tanda"}
              </span>
            </label>
            {errorTanda && <p className={styles.error}>{errorTanda}</p>}
          </section>

          {avisoTanda && (
            <section
              className={`${styles.avisoCuenta} ${avisoTanda.requiereAtencion ? styles.avisoCuentaFuerte : ""}`}
              aria-live="polite"
            >
              <p>{avisoTanda.mensaje}</p>
              {avisoTanda.requiereAtencion && (
                <button
                  type="button"
                  className={styles.botonSecundario}
                  onClick={() =>
                    setAvisoTanda((actual) => (actual ? { ...actual, requiereAtencion: false } : null))
                  }
                >
                  Entendido, continuar
                </button>
              )}
            </section>
          )}

          {/* --- Lista de confirmación: el arte, grande ------------------------------ */}
          {pendientes.length > 0 && (
            <section className={styles.tarjeta}>
              <h2 className={styles.subtitulo}>
                Confirma estas {pendientes.length} {pendientes.length === 1 ? "carta" : "cartas"}
              </h2>
              <ul className={styles.listaFilas}>
                {pendientes.map((fila) => (
                  <li key={fila.key} className={styles.fila}>
                    <div className={styles.filaArte}>
                      {fila.carta?.image_url ? (
                        <img src={fila.carta.image_url} alt="" className={styles.filaImagen} loading="lazy" />
                      ) : (
                        <div className={styles.filaImagenVacia} aria-hidden="true">
                          ?
                        </div>
                      )}
                    </div>
                    <div className={styles.filaDatos}>
                      {fila.carta ? (
                        <>
                          <p className={styles.filaNombre}>{fila.carta.name}</p>
                          <p className={styles.filaDetalle}>
                            {fila.carta.set_name} · {fila.carta.local_id}
                            {fila.carta.set_card_count ? `/${fila.carta.set_card_count}` : ""}
                          </p>
                          {fila.necesitaRevision && (
                            <p className={styles.filaAviso}>
                              Revisar: {fila.motivo || "confianza baja en la lectura."}
                            </p>
                          )}
                          <div className={styles.grupoChips}>
                            {CHIPS_MODERNOS.map(({ label, texto }) => (
                              <button
                                key={label}
                                type="button"
                                className={`${styles.chip} ${fila.varianteLabel === label ? styles.chipActivo : ""}`}
                                aria-pressed={fila.varianteLabel === label}
                                onClick={() => seleccionarVarianteFila(fila.key, label)}
                              >
                                {texto}
                              </button>
                            ))}
                            {esSetWotc(fila.carta) &&
                              CHIPS_VINTAGE.map(({ label, texto }) => (
                                <button
                                  key={label}
                                  type="button"
                                  className={`${styles.chip} ${fila.varianteLabel === label ? styles.chipActivo : ""}`}
                                  aria-pressed={fila.varianteLabel === label}
                                  onClick={() => seleccionarVarianteFila(fila.key, label)}
                                >
                                  {texto}
                                </button>
                              ))}
                          </div>
                          {fila.varianteLabel && !fila.varianteResuelta && (
                            <p className={styles.filaAviso}>Esta carta no tiene esa variante.</p>
                          )}
                          {fila.necesitaRevision && (
                            <button
                              type="button"
                              className={styles.enlaceCorregir}
                              onClick={() => alternarCorregir(fila.key)}
                            >
                              {fila.corrigiendo ? "Cancelar corrección" : "Corregir esta carta"}
                            </button>
                          )}
                        </>
                      ) : (
                        <>
                          <p className={styles.filaAviso}>
                            {fila.motivo || "No se pudo identificar esta carta."}
                            {fila.reconocido?.species ? ` Se leyó ${fila.reconocido.species}.` : ""}
                          </p>
                        </>
                      )}

                      {(fila.corrigiendo || !fila.carta) && (
                        <div className={styles.filaCorreccion}>
                          <label className={styles.campo}>
                            <span>Set</span>
                            <input
                              type="text"
                              value={fila.setId}
                              onChange={(e) => actualizarBusquedaFila(fila.key, "setId", e.target.value)}
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
                              value={fila.numero}
                              onChange={(e) => actualizarBusquedaFila(fila.key, "numero", e.target.value)}
                              placeholder="001/165"
                            />
                          </label>
                          <button
                            type="button"
                            className={styles.botonSecundario}
                            onClick={() => corregirFila(fila.key)}
                            disabled={fila.buscando}
                          >
                            {fila.buscando ? "Buscando…" : "Buscar"}
                          </button>
                          {fila.errorBusqueda && <p className={styles.error}>{fila.errorBusqueda}</p>}
                        </div>
                      )}
                    </div>
                    <button
                      type="button"
                      className={styles.filaQuitar}
                      onClick={() => quitarFila(fila.key)}
                      aria-label={`Quitar ${fila.carta?.name ?? "esta carta"} de la lista`}
                    >
                      Quitar
                    </button>
                  </li>
                ))}
              </ul>

              {errorGuardarEjemplares && <p className={styles.error}>{errorGuardarEjemplares}</p>}
              <button
                type="button"
                className={styles.botonPrimario}
                disabled={!puedeGuardarPendientes}
                onClick={guardarPendientes}
              >
                {guardandoEjemplares
                  ? "Guardando…"
                  : `Guardar ${filasListas.length} ${filasListas.length === 1 ? "carta" : "cartas"}`}
              </button>
              {filasListas.length !== pendientes.length && (
                <p className={styles.hint}>
                  Falta elegir carta o variante en {pendientes.length - filasListas.length}{" "}
                  {pendientes.length - filasListas.length === 1 ? "fila" : "filas"}.
                </p>
              )}
            </section>
          )}

          {/* --- Añadir una carta a mano ------------------------------------------- */}
          <section className={styles.tarjeta}>
            <h2 className={styles.subtitulo}>Añadir una carta a mano</h2>
            <div className={styles.fila2Col}>
              <label className={styles.campo}>
                <span>Set</span>
                <input
                  type="text"
                  value={manualSetId}
                  onChange={(e) => setManualSetId(e.target.value)}
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
                  value={manualNumero}
                  onChange={(e) => setManualNumero(e.target.value)}
                  placeholder="001/165"
                />
              </label>
            </div>
            {errorManual && <p className={styles.error}>{errorManual}</p>}
            <button
              type="button"
              className={styles.botonSecundario}
              onClick={agregarCartaManual}
              disabled={buscandoManual}
            >
              {buscandoManual ? "Buscando…" : "Añadir a la lista"}
            </button>
          </section>

          {/* --- Relleno: cartas bulk sin foto ni identificar --------------------- */}
          <section className={styles.tarjeta}>
            <h2 className={styles.subtitulo}>Relleno</h2>
            <p className={styles.hint}>
              Cartas comunes del lote que no vale la pena identificar una por una. Entran a costo
              $0 y las demás absorben el total.
            </p>
            <div className={styles.fila2Col}>
              <label className={styles.campo}>
                <span>Cuántas</span>
                <input
                  type="number"
                  inputMode="numeric"
                  min="1"
                  value={rellenoCantidad}
                  onChange={(e) => setRellenoCantidad(e.target.value)}
                  placeholder="20"
                />
              </label>
              <button
                type="button"
                className={styles.botonSecundario}
                onClick={onAgregarRelleno}
                disabled={guardandoRelleno}
              >
                {guardandoRelleno ? "Añadiendo…" : "Añadir relleno"}
              </button>
            </div>
            {errorRelleno && <p className={styles.error}>{errorRelleno}</p>}
          </section>

          {/* --- Guardadas + reparto ------------------------------------------------ */}
          {guardadas.length > 0 && (
            <section className={styles.tarjeta}>
              <h2 className={styles.subtitulo}>
                {guardadas.length} {guardadas.length === 1 ? "ejemplar guardado" : "ejemplares guardados"}
              </h2>
              <ul className={styles.listaGuardadas}>
                {guardadas.map((g) => (
                  <li key={g.id} className={styles.filaGuardada}>
                    <span className={styles.filaGuardadaNombre}>
                      {g.carta ? g.carta.name : "Relleno"}
                      {g.carta && g.varianteLabel ? ` · ${g.varianteLabel}` : ""}
                    </span>
                    <span className={styles.filaGuardadaCosto}>
                      {g.costoUsd != null ? `$${g.costoUsd.toFixed(2)}` : "—"}
                    </span>
                  </li>
                ))}
              </ul>

              <h3 className={styles.subtitulo}>Repartir el costo</h3>
              <div className={styles.grupoChips}>
                {METODOS.map(({ value, texto }) => (
                  <button
                    key={value}
                    type="button"
                    className={`${styles.chip} ${metodo === value ? styles.chipActivo : ""}`}
                    aria-pressed={metodo === value}
                    onClick={() => (value === "manual" ? setMetodo("manual") : aplicarReparto(value))}
                    disabled={repartiendo}
                  >
                    {texto}
                  </button>
                ))}
              </div>

              {metodo === "manual" && (
                <div className={styles.repartoManual}>
                  {guardadasElegibles.map((g) => (
                    <label key={g.id} className={styles.campoManual}>
                      <span>{g.carta ? g.carta.name : `Ejemplar #${g.id}`}</span>
                      <input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.01"
                        value={costosManuales[g.id] ?? ""}
                        onChange={(e) =>
                          setCostosManuales((prev) => ({ ...prev, [g.id]: e.target.value }))
                        }
                        placeholder="0.00"
                      />
                    </label>
                  ))}
                  {guardadas.length > guardadasElegibles.length && (
                    <p className={styles.hint}>
                      El relleno no entra en esta lista: siempre le toca $0 y no participa del
                      reparto.
                    </p>
                  )}
                  <p className={manualCuadra ? styles.hint : styles.error}>
                    Suma escrita: ${(totalManualCentavos / 100).toFixed(2)} de $
                    {compra.total_usd.toFixed(2)}
                    {manualCuadra ? " — cuadra." : " — todavía no cuadra."}
                  </p>
                  <button
                    type="button"
                    className={styles.botonSecundario}
                    disabled={!manualCuadra || repartiendo}
                    onClick={() => aplicarReparto("manual")}
                  >
                    {repartiendo ? "Aplicando…" : "Aplicar reparto manual"}
                  </button>
                </div>
              )}

              {errorReparto && <p className={styles.error}>{errorReparto}</p>}

              {repartoAplicado && sumaAsignada != null && (
                <p className={styles.confirmacionReparto} aria-live="polite">
                  Suma asignada: ${sumaAsignada.toFixed(2)} de ${compra.total_usd.toFixed(2)} —{" "}
                  {Math.round(sumaAsignada * 100) === totalObjetivoCentavos
                    ? "cuadra exactamente."
                    : "revisa el redondeo."}
                </p>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
