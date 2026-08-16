import type { NextRequest } from "next/server";

const BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

// La foto viaja como el cuerpo crudo del POST (igual que el backend la
// recibe, ver `purchases.py`): se reenvía tal cual, sin decodificarla a
// JSON en el medio.
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const contentType = request.headers.get("content-type") || "image/jpeg";
  const cuerpo = await request.arrayBuffer();
  const respuesta = await fetch(`${BASE_URL}/compras/${id}/tanda`, {
    method: "POST",
    headers: { "Content-Type": contentType },
    body: cuerpo,
  });
  const datos = await respuesta.text();
  return new Response(datos, {
    status: respuesta.status,
    headers: { "Content-Type": "application/json" },
  });
}
