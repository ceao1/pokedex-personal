-- `owned_copy_variante_completa` (FK compuesta card_id+variant_id) usa
-- MATCH SIMPLE por default, que se salta la validación por completo cuando
-- cualquiera de las dos columnas es null. Un ejemplar puede legítimamente
-- tener card_id sin variant_id todavía (el dueño identificó la carta pero
-- no eligió el print/variante) -- eso no debe bloquearse. Lo que sí debe
-- bloquearse es variant_id sin card_id: no tiene sentido guardar una
-- variante sin decir de qué carta, y sin este check pasaba sin que la base
-- lo rechazara.
--
-- Este check exige que, si hay variant_id, también haya card_id. Con eso,
-- cada vez que variant_id no es null, card_id tampoco lo es, y la FK
-- compuesta queda siempre evaluada.
alter table app.owned_copy
  add constraint owned_copy_variant_id_requiere_card_id check (
    variant_id is null or card_id is not null
  );
