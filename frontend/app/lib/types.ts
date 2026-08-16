export type Pokemon = {
  dex_number: number;
  name: string;
  wishlist_count: number;
  sin_resolver: number;
  owned_count: number;
  primary_image_url: string | null;
  primary_card_name: string | null;
  primary_price_usd: number | null;
  primary_price_captured_at: string | null;
};

export type WishlistItem = {
  id: number;
  dex_number: number | null;
  card_id: string | null;
  variant_label: string | null;
  raw_text: string;
  source_option: string;
  auto_resolved: boolean;
  is_favorite: boolean;
  status: string;
  reference_value_usd: number | null;
  card_name: string | null;
  image_url: string | null;
  rarity: string | null;
  set_name: string | null;
  price_usd: number | null;
  price_captured_at: string | null;
};

/** Un ejemplar propio, tal como lo devuelve `GET /pokedex/{dex}` en
 * `copies`. La foto ya viene firmada (o `null` si no hay o si firmar
 * falló) — nunca es la ruta cruda del bucket privado. */
export type OwnedCopyDetail = {
  id: number;
  card_id: string | null;
  card_name: string | null;
  set_name: string | null;
  local_id: string | null;
  variant_label: string | null;
  condition: string | null;
  purchase_price_usd: number | null;
  photo_url: string | null;
  notes: string | null;
  created_at: string;
};

export type PokemonDetail = Pokemon & {
  options: WishlistItem[];
  copies: OwnedCopyDetail[];
};

/** Un ejemplar cuya carta no pertenece al proyecto de los 151, tal como lo
 * devuelve `GET /otras-cartas`: de otra generación, sin `dex_number` en el
 * catálogo, o sin carta identificada todavía. `photo_url` es la foto propia
 * ya firmada; `image_url` es el arte del catálogo, el respaldo cuando no
 * hay foto propia. */
export type OtraCarta = {
  id: number;
  card_id: string | null;
  card_name: string | null;
  set_name: string | null;
  local_id: string | null;
  dex_number: number | null;
  image_url: string | null;
  variant_label: string | null;
  condition: string | null;
  purchase_price_usd: number | null;
  photo_url: string | null;
  notes: string | null;
  created_at: string;
};

export type Variant = {
  id: string;
  type: string;
  subtype: string | null;
  stamp: string[];
  foil: string | null;
  price_usd: number | null;
  price_captured_at: string | null;
};

export type Card = {
  id: string;
  name: string;
  set_id: string;
  set_name: string;
  local_id: string;
  set_card_count: number | null;
  rarity: string | null;
  image_url: string | null;
  dex_number: number | null;
  variants: Variant[];
};

export type Uploads = {
  front: string;
  thumb: string;
};

export type StartCapture = {
  client_draft_id: string;
  uploads: Uploads;
};

/** Coincide con `pokedex.catalog.variants.VariantLabel` en el backend. */
export type VariantLabel =
  | "normal"
  | "reverse"
  | "holo"
  | "first_edition"
  | "shadowless"
  | "unlimited";

export type OwnedCopyIn = {
  card_id?: string | null;
  variant_id?: string | null;
  variant_label?: VariantLabel | null;
  condition?: string | null;
  purchase_price_usd?: number | string | null;
  source_type?: string | null;
  binder_id?: number | null;
  page?: number | null;
  capture_status?: string | null;
  lifecycle_status?: string | null;
  notes?: string | null;
};

/** Lo que el modelo leyó de la foto, sin validar todavía contra el
 * catálogo (`RecognitionOut` en el backend). Confirmado contra el
 * contrato real: trae `species`/`dex_number` además de las seis claves
 * documentadas en el plan -- justo lo que permite responder "cuál
 * Pokémon es" aunque el set o el número no resuelvan. */
export type Recognition = {
  name: string | null;
  set_name: string | null;
  number: string | null;
  rarity: string | null;
  species: string | null;
  dex_number: number | null;
  confidence: number;
  needs_review: boolean;
};

/** Respuesta de `POST /captures/{client_draft_id}/identificar`. `carta` solo
 * viene si `(set, número)` resolvió contra el catálogo real -- una
 * identificación nunca se acepta por su sola palabra. */
export type Identificacion = {
  reconocido: Recognition;
  carta: Card | null;
  necesita_revision: boolean;
  motivo: string;
};

export type OwnedCopy = {
  id: number;
  client_draft_id: string;
  card_id: string | null;
  variant_id: string | null;
  variant_label: string | null;
  condition: string | null;
  photo_front_url: string | null;
  photo_thumb_url: string | null;
  purchase_price_usd: number | null;
  source_type: string | null;
  binder_id: number | null;
  page: number | null;
  capture_status: string;
  lifecycle_status: string;
  notes: string | null;
};
