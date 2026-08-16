import type { Pokemon, PokemonDetail } from "./types";

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
