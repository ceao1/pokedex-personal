-- Corrige la identidad de app.card_variant.
--
-- El `variantId` de TCGdex identifica una *forma* de variante (ej. "normal,
-- tamaño estándar"), no una combinación única de carta+variante: TCGdex
-- reutiliza el mismo variantId entre cartas distintas del mismo set (ej.
-- `endfynwn4n10gzq` aparece igual en sv03.5-001, sv03.5-002, sv03.5-004 y
-- sv03.5-005). El diseño original lo tomó como clave primaria por sí solo,
-- así que `_UPSERT_VARIANT` (on conflict (id) do update, sin tocar card_id)
-- hacía que la segunda carta que traía un variantId compartido pisara en el
-- lugar la fila de la primera, dejándola atada al card_id equivocado. La
-- identidad real de una fila de card_variant es el par (card_id, id).
--
-- La tabla local queda con datos corruptos por el defecto descrito arriba.
-- Como esta es una base de desarrollo y el espejo se puede rehacer bajo
-- demanda contra TCGdex, se vacía antes de cambiar la clave en vez de
-- intentar reconciliar filas que ya perdieron su card_id original.
truncate table app.card_variant;

alter table app.card_variant drop constraint card_variant_pkey;
alter table app.card_variant add constraint card_variant_pkey primary key (card_id, id);
