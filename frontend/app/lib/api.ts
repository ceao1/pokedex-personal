import type { Card, OwnedCopy, OwnedCopyIn, Pokemon, PokemonDetail, StartCapture } from "./types";

const BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`El backend respondió ${response.status} en ${path}`);
  }
  return response.json() as Promise<T>;
}

export function fetchPokedex(): Promise<Pokemon[]> {
  return get<Pokemon[]>("/pokedex");
}

export function fetchPokemon(dexNumber: number): Promise<PokemonDetail> {
  return get<PokemonDetail>(`/pokedex/${dexNumber}`);
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
 * universal. Verificado contra el navegador real: en `IP-DE-RED-LOCAL`
 * `crypto.randomUUID` es `undefined` y esto rompía toda captura antes de
 * la primera llamada de red. */
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
