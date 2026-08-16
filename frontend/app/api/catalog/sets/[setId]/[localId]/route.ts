import type { NextRequest } from "next/server";

const BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ setId: string; localId: string }> }
) {
  const { setId, localId } = await params;
  const respuesta = await fetch(
    `${BASE_URL}/catalog/sets/${encodeURIComponent(setId)}/${encodeURIComponent(localId)}`,
    { cache: "no-store" }
  );
  const datos = await respuesta.text();
  return new Response(datos, {
    status: respuesta.status,
    headers: { "Content-Type": "application/json" },
  });
}
