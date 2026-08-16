import type { NextRequest } from "next/server";

// Reenvía a FastAPI desde el servidor de Next, no desde el navegador: el
// backend no manda cabeceras CORS y el celular abre la app por la IP de la
// red local en un puerto distinto al de FastAPI (ver `app/lib/api.ts`).
const BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export async function POST(request: NextRequest) {
  const body = await request.text();
  const respuesta = await fetch(`${BASE_URL}/captures`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  const datos = await respuesta.text();
  return new Response(datos, {
    status: respuesta.status,
    headers: { "Content-Type": "application/json" },
  });
}
