-- El dexId de TCGdex falta en cartas que no pertenecen al set 151 pero cuyo
-- Pokémon sí (ej. "Erika's Gloom" en Ascended Heroes: dexId null, pero es un
-- Gloom real, slot 44). La identificación por foto puede inferir el
-- dex_number validándolo contra app.pokemon (dos señales de acuerdo: el
-- número de colección resuelto y la especie que dice el modelo). Esta
-- columna distingue esa inferencia del dato real de catálogo: nunca deben
-- verse iguales en la misma columna sin poder distinguirlos, porque una
-- auditoría de precio o de dex futura necesita saber cuál es cuál.
alter table app.card
  add column dex_number_inferido boolean not null default false;
