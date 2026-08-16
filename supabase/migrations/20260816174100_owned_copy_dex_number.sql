-- Lo que el dueño pidió: "permite que el set quede vacío, si es posible
-- identificarlo bien, si no no pasa nada". Un ejemplar puede resolverse
-- por especie (la foto confirmó el Pokémon, ej. por dexId del modelo
-- validado contra app.pokemon) sin que la carta exacta -- set y número --
-- se conozca todavía. Este casillero cuelga ese ejemplar de su lugar en el
-- 151 aunque `card_id` siga en null.
--
-- La carta manda cuando existe: en cualquier consulta que hoy lee
-- `card.dex_number`, la lectura correcta pasa a ser
-- `coalesce(card.dex_number, owned_copy.dex_number)` (ver
-- `collection/repository.py` y `wishlist/repository.py`). Este valor es
-- solo el respaldo.
alter table app.owned_copy
  add column dex_number integer;

alter table app.owned_copy
  add constraint owned_copy_dex_number_valido check (
    dex_number is null or dex_number between 1 and 151
  );
