import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, fetchCard, fetchPokemon } from "../../lib/api";
import { Ficha } from "./Ficha";
import type { OwnedCopyDetail } from "../../lib/types";

type Params = { dex: string };

export async function generateMetadata({ params }: { params: Promise<Params> }) {
  const { dex } = await params;
  return { title: `Pokémon ${dex} — Pokédex viviente` };
}

export default async function PokemonPage({ params }: { params: Promise<Params> }) {
  const { dex } = await params;
  const dexNumber = Number(dex);
  if (!Number.isInteger(dexNumber) || dexNumber < 1) {
    notFound();
  }

  let pokemon;
  try {
    pokemon = await fetchPokemon(dexNumber);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
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

  // El arte de catálogo de cada impresión concreta no viaja en `copies`
  // (solo la foto del dueño, si la hay), así que se completa acá con una
  // llamada por carta distinta -- solo para los ejemplares sin foto propia.
  const idsSinFoto = Array.from(
    new Set(
      pokemon.copies
        .filter((copia) => !copia.photo_url && copia.card_id)
        .map((copia) => copia.card_id as string)
    )
  );

  const artePorCarta = new Map<string, string | null>();
  await Promise.all(
    idsSinFoto.map(async (cardId) => {
      try {
        const carta = await fetchCard(cardId);
        artePorCarta.set(cardId, carta.image_url);
      } catch {
        artePorCarta.set(cardId, null);
      }
    })
  );

  const copiasConArte: (OwnedCopyDetail & { arte_catalogo: string | null })[] = pokemon.copies.map(
    (copia) => ({
      ...copia,
      arte_catalogo: copia.card_id ? (artePorCarta.get(copia.card_id) ?? null) : null,
    })
  );

  return <Ficha pokemon={pokemon} copias={copiasConArte} />;
}
