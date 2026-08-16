/**
 * Persistencia local de las fotos de una captura en IndexedDB.
 *
 * La spec (§6 paso 1, §10) exige que ambos blobs redimensionados existan
 * en el dispositivo *antes* de tocar la red: la carta estuvo en la mano
 * del dueño en ese momento y puede no estarlo después, así que un fallo
 * de red, una recarga o iOS matando la PWA en segundo plano no puede
 * costarle la foto. Este módulo es la única pieza con esa
 * responsabilidad -- `Captura.tsx` solo la usa, no sabe cómo se guarda.
 *
 * Sin dependencias nuevas: es la API de IndexedDB del navegador, a mano.
 */

const DB_NOMBRE = "pokedex-fotos-pendientes";
const DB_VERSION = 1;
const ALMACEN = "fotos";

export type FotoPendiente = {
  clientDraftId: string;
  front: Blob;
  thumb: Blob;
  guardadaEn: number;
};

function haySoporte(): boolean {
  return typeof indexedDB !== "undefined";
}

function abrirDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const solicitud = indexedDB.open(DB_NOMBRE, DB_VERSION);
    solicitud.onupgradeneeded = () => {
      const db = solicitud.result;
      if (!db.objectStoreNames.contains(ALMACEN)) {
        db.createObjectStore(ALMACEN, { keyPath: "clientDraftId" });
      }
    };
    solicitud.onsuccess = () => resolve(solicitud.result);
    solicitud.onerror = () =>
      reject(solicitud.error ?? new Error("No se pudo abrir la base local de fotos."));
  });
}

/** Ejecuta una operación y espera a que la *transacción* confirme antes de
 * resolver (no solo a que la request individual tenga éxito): así, cuando
 * el llamador sigue adelante, el blob ya quedó escrito de verdad. */
async function conAlmacen<T>(
  modo: IDBTransactionMode,
  fn: (almacen: IDBObjectStore) => IDBRequest<T>
): Promise<T> {
  const db = await abrirDb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction(ALMACEN, modo);
      const almacen = tx.objectStore(ALMACEN);
      const solicitud = fn(almacen);
      let resultado: T;
      solicitud.onsuccess = () => {
        resultado = solicitud.result;
      };
      solicitud.onerror = () =>
        reject(solicitud.error ?? new Error("Error al leer o escribir la foto local."));
      tx.oncomplete = () => resolve(resultado);
      tx.onerror = () => reject(tx.error ?? new Error("Error al leer o escribir la foto local."));
      tx.onabort = () => reject(tx.error ?? new Error("Se canceló la operación local."));
    });
  } finally {
    db.close();
  }
}

/** Guarda (o reemplaza) los dos blobs de una captura. Se llama justo
 * después de redimensionar y antes de la primera llamada de red.
 *
 * Nunca lanza: si IndexedDB no existe o falla (cuota llena, modo
 * privado), se registra un aviso y se sigue -- persistir localmente es
 * la red de seguridad, no debe bloquear el intento real de subida. */
export async function guardarFotoPendiente(
  clientDraftId: string,
  front: Blob,
  thumb: Blob
): Promise<void> {
  if (!haySoporte()) return;
  const registro: FotoPendiente = { clientDraftId, front, thumb, guardadaEn: Date.now() };
  try {
    await conAlmacen("readwrite", (almacen) => almacen.put(registro));
  } catch (error) {
    console.warn("No se pudo guardar la foto en IndexedDB", error);
  }
}

/** Trae los blobs de una captura puntual, para reintentar una subida sin
 * volver a pedirle la foto al dueño. */
export async function obtenerFotoPendiente(clientDraftId: string): Promise<FotoPendiente | null> {
  if (!haySoporte()) return null;
  const resultado = await conAlmacen<FotoPendiente | undefined>("readonly", (almacen) =>
    almacen.get(clientDraftId)
  );
  return resultado ?? null;
}

/** Todas las fotos que quedaron pendientes de subir: de esta sesión o de
 * una anterior (recarga, pestaña cerrada, iOS matando la PWA). */
export async function listarFotosPendientes(): Promise<FotoPendiente[]> {
  if (!haySoporte()) return [];
  return conAlmacen<FotoPendiente[]>("readonly", (almacen) => almacen.getAll());
}

/** Se llama solo cuando el backend ya confirmó la subida (`photo-uploaded`):
 * una foto subida con éxito no debe acumularse para siempre en el navegador. */
export async function eliminarFotoPendiente(clientDraftId: string): Promise<void> {
  if (!haySoporte()) return;
  await conAlmacen("readwrite", (almacen) => almacen.delete(clientDraftId));
}
