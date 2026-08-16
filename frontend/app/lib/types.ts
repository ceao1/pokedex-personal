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
