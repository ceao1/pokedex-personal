export type Pokemon = {
  dex_number: number;
  name: string;
  wishlist_count: number;
  sin_resolver: number;
  owned_count: number;
  primary_image_url: string | null;
  primary_card_name: string | null;
  primary_price_usd: number | null;
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
};

export type PokemonDetail = Pokemon & { options: WishlistItem[] };

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
