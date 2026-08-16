import type { NextRequest } from "next/server";

const BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ clientDraftId: string }> }
) {
  const { clientDraftId } = await params;
  const respuesta = await fetch(`${BASE_URL}/captures/${clientDraftId}/identificar`, {
    method: "POST",
  });
  const datos = await respuesta.text();
  return new Response(datos, {
    status: respuesta.status,
    headers: { "Content-Type": "application/json" },
  });
}
