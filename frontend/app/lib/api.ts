import type {
  AllocationMethod,
  Card,
  EjemplarConfirmadoIn,
  Identificacion,
  IdsOut,
  OtraCarta,
  OwnedCopy,
  OwnedCopyIn,
  Pokemon,
  PokemonDetail,
  PurchaseDetailOut,
  PurchaseOut,
  PurchaseSourceType,
  RepartirOut,
  StartCapture,
  TandaOut,
} from "./types";

const BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

/** Lleva el status HTTP a cuestas para que quien llama pueda distinguir
 * "no existe" (404, la pantalla lo dice) de "el backend no responde"
 * (cualquier otro fallo, mensaje distinto). */
export class ApiError extends Error {
  status: number;
  constructor(status: number, path: string) {
    super(`El backend respondió ${status} en ${path}`);
    this.status = status;
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(response.status, path);
  }
  return response.json() as Promise<T>;
}

export function fetchPokedex(): Promise<Pokemon[]> {
  return get<Pokemon[]>("/pokedex");
}

export function fetchPokemon(dexNumber: number): Promise<PokemonDetail> {
  return get<PokemonDetail>(`/pokedex/${dexNumber}`);
}

/** Las últimas páginas del binder: ejemplares cuya carta no es de los 151.
 * Mismo `no-store` que el resto de `get`, para que el riel y esta pantalla
 * nunca muestren un conteo viejo tras registrar una carta. */
export function fetchOtrasCartas(): Promise<OtraCarta[]> {
  return get<OtraCarta[]>("/otras-cartas");
}

// Las escrituras de captura corren en el navegador, no en el servidor de
// Next, así que van contra `/api/...` (mismo origen que la página) en vez de
// directo contra FastAPI: el backend no manda cabeceras CORS, y el celular
// abre la app por la IP de la red local en un puerto distinto al de FastAPI.
// Las rutas de `app/api/captures/...` son el único lugar que reenvía a
// `BASE_URL`; ver ese directorio.

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`El backend respondió ${response.status} en ${path}`);
  }
  return response.json() as Promise<T>;
}

async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`El backend respondió ${response.status} en ${path}`);
  }
  return response.json() as Promise<T>;
}

async function apiGetLocal<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`El backend respondió ${response.status} en ${path}`);
  }
  return response.json() as Promise<T>;
}

/** `crypto.randomUUID` exige contexto seguro (HTTPS o `localhost`); el
 * celular entra por la IP de la red local sin TLS, así que ahí no existe
 * y hay que generar el UUID a mano con `getRandomValues`, que sí es
 * universal. Verificado contra el navegador real: servido por IP de red
 * local sin TLS, `crypto.randomUUID` es `undefined` y esto rompía toda
 * captura antes de la primera llamada de red. */
export function nuevoClientDraftId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10, 16).join(""),
  ].join("-");
}

export function crearCaptura(clientDraftId: string): Promise<StartCapture> {
  return apiPost<StartCapture>("/api/captures", { client_draft_id: clientDraftId });
}

/** Sube directo al bucket de Supabase Storage con la URL firmada: nunca pasa
 * por el backend, así el celular no espera un proxy multipart. */
export async function subirFoto(signedUrl: string, contenido: Blob): Promise<void> {
  const response = await fetch(signedUrl, {
    method: "PUT",
    headers: { "Content-Type": "image/jpeg" },
    body: contenido,
  });
  if (!response.ok) {
    throw new Error(`La subida de la foto respondió ${response.status}`);
  }
}

export function marcarFotoSubida(clientDraftId: string): Promise<OwnedCopy> {
  return apiPost<OwnedCopy>(`/api/captures/${clientDraftId}/photo-uploaded`, {});
}

/** Dispara la identificación por foto en segundo plano. Nunca lanza: sin
 * llave configurada el backend responde 503, y un problema de red es
 * exactamente igual de silencioso -- en ambos casos el registro a mano
 * sigue funcionando como si esto no existiera. `null` significa "no hay
 * propuesta", nunca "algo se rompió". */
export async function identificarCaptura(clientDraftId: string): Promise<Identificacion | null> {
  try {
    const response = await fetch(`/api/captures/${clientDraftId}/identificar`, {
      method: "POST",
    });
    if (!response.ok) return null;
    return (await response.json()) as Identificacion;
  } catch {
    return null;
  }
}

export function actualizarCaptura(
  clientDraftId: string,
  datos: OwnedCopyIn
): Promise<OwnedCopy> {
  return apiPatch<OwnedCopy>(`/api/captures/${clientDraftId}`, datos);
}

export function buscarCarta(setId: string, localId: string): Promise<Card> {
  return apiGetLocal<Card>(
    `/api/catalog/sets/${encodeURIComponent(setId)}/${encodeURIComponent(localId)}`
  );
}

/** El arte de una impresión concreta. `GET /pokedex/{dex}` no manda el arte
 * de catálogo de cada ejemplar propio (solo la foto del dueño, si hay), así
 * que la ficha lo completa con esta llamada cuando falta la foto. */
export function fetchCard(cardId: string): Promise<Card> {
  return get<Card>(`/catalog/cards/${encodeURIComponent(cardId)}`);
}

// --- Compras (sobres, lotes y fotos por tanda) ------------------------------
//
// Mismo motivo que las rutas de captura: estas escrituras corren en el
// navegador del celular, que entra por la IP de la red local, así que van
// contra `/api/compras/...` (mismo origen) en vez de directo contra
// FastAPI. Ver `app/api/compras/...` para los proxies.

export function crearCompra(
  sourceType: PurchaseSourceType,
  totalUsd: string,
  notes: string | null = null
): Promise<PurchaseOut> {
  return apiPost<PurchaseOut>("/api/compras", { source_type: sourceType, total_usd: totalUsd, notes });
}

export function fetchCompra(purchaseId: number): Promise<PurchaseDetailOut> {
  return apiGetLocal<PurchaseDetailOut>(`/api/compras/${purchaseId}`);
}

/** Identifica varias cartas en una foto -- **no guarda nada**. La foto viaja
 * como cuerpo crudo, igual que hace el backend con `python-multipart` fuera
 * de la lista de dependencias (ver `purchases.py`). Puede tardar bastante
 * (una tanda de doce cartas midió ~17s en la medición del plan), así que
 * quien llama es responsable de mostrar un estado de espera. */
export async function subirTanda(purchaseId: number, foto: Blob): Promise<TandaOut> {
  const response = await fetch(`/api/compras/${purchaseId}/tanda`, {
    method: "POST",
    headers: { "Content-Type": "image/jpeg" },
    body: foto,
  });
  if (!response.ok) {
    const detalle = await response.json().catch(() => null);
    throw new Error(
      (detalle && typeof detalle.detail === "string" && detalle.detail) ||
        `El backend respondió ${response.status} al leer la foto.`
    );
  }
  return (await response.json()) as TandaOut;
}

/** Guarda la lista que el dueño confirmó -- nunca al revés. */
export function confirmarEjemplares(
  purchaseId: number,
  ejemplares: EjemplarConfirmadoIn[]
): Promise<IdsOut> {
  return apiPost<IdsOut>(`/api/compras/${purchaseId}/ejemplares`, { ejemplares });
}

/** N ejemplares bulk, sin carta ni foto, a costo cero hasta que se reparte. */
export function agregarRelleno(purchaseId: number, cantidad: number): Promise<IdsOut> {
  return apiPost<IdsOut>(`/api/compras/${purchaseId}/relleno`, { cantidad });
}

/** Aplica el método de reparto. Recalcular con otro método no toca
 * `total_usd`, así que llamarlo más de una vez es seguro. */
export function repartirCompra(
  purchaseId: number,
  method: AllocationMethod,
  costos?: Record<number, string> | null
): Promise<RepartirOut> {
  return apiPost<RepartirOut>(`/api/compras/${purchaseId}/repartir`, { method, costos: costos ?? null });
}
