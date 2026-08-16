import { Binder } from "./binder/Binder";
import { fetchOtrasCartas, fetchPokedex } from "./lib/api";

export default async function Home() {
  try {
    const [pokedex, otrasCartas] = await Promise.all([fetchPokedex(), fetchOtrasCartas()]);
    if (pokedex.length === 0) {
      return (
        <main style={{ padding: "3rem", maxWidth: "42ch" }}>
          <h1>El binder está vacío</h1>
          <p>
            Corre el import del Excel para sembrar los 151:{" "}
            <code>uv run python -m pokedex.cli import-excel ../Pokedex_Viviente_151.xlsx</code>
          </p>
        </main>
      );
    }
    return <Binder pokedex={pokedex} otrasCartasCount={otrasCartas.length} />;
  } catch {
    return (
      <main style={{ padding: "3rem", maxWidth: "42ch" }}>
        <h1>No hay conexión con el backend</h1>
        <p>
          Levanta FastAPI en el puerto 8000:{" "}
          <code>cd backend && uv run uvicorn pokedex.api.main:app --app-dir src</code>
        </p>
      </main>
    );
  }
}
