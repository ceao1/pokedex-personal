import Link from "next/link";
import { fetchOtrasCartas } from "../lib/api";
import { Otras } from "./Otras";

export const metadata = {
  title: "Otras cartas — Pokédex viviente",
};

export default async function OtrasPage() {
  try {
    const cartas = await fetchOtrasCartas();
    return <Otras cartas={cartas} />;
  } catch {
    return (
      <main style={{ padding: "3rem", maxWidth: "42ch" }}>
        <h1>No hay conexión con el backend</h1>
        <p>
          Levanta FastAPI en el puerto 8000:{" "}
          <code>cd backend && uv run uvicorn pokedex.api.main:app --app-dir src</code>
        </p>
        <p>
          <Link href="/">‹ Volver al binder</Link>
        </p>
      </main>
    );
  }
}
