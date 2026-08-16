/**
 * Redimensiona una imagen en el navegador antes de subirla. Compartido por
 * `/registrar` (una carta) y `/compras/nueva` (una tanda de varias): las dos
 * pantallas suben fotos desde el celular y ninguna debe mandar el archivo
 * crudo de la cámara (varios MB) a la red.
 */
export async function redimensionar(
  archivo: Blob,
  ladoMayor: number,
  calidad = 0.85
): Promise<Blob> {
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
