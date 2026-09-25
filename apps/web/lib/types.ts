/**
 * FastAPI（`/api/v1`）の応答型。Wave 1 の API 契約（コーディネーター指示・設計仕様書 4.2）を写したもの。
 * `apps/api/openapi.json` と食い違いが見つかったらここを直す。
 */

export type Gender = "women" | "men" | "kids_teen" | "all";

export interface CategoryChild {
  slug: string;
  name: string;
  product_count: number;
}

export interface Category {
  slug: string;
  name: string;
  gender: Gender;
  children: CategoryChild[];
}

export interface CategoriesResponse {
  categories: Category[];
}

/** DS-API-002 一覧の 1 件 */
export interface ProductSummary {
  id: number;
  name: string;
  price_incl_tax: number;
  /** `products/001/1.jpg` の形。openapi.json では nullable（画像未登録） */
  image_path: string | null;
  colors: string[];
  sold_out: boolean;
}

export interface ProductListResponse {
  items: ProductSummary[];
  page: number;
  per_page: number;
  total: number;
  has_more: boolean;
}

export interface Variant {
  variant_id: number;
  color: string;
  size: string;
  in_stock: boolean;
}

/** 詳細の関連商品（colors は無い） */
export interface RelatedProduct {
  id: number;
  name: string;
  price_incl_tax: number;
  image_path: string | null;
  sold_out: boolean;
}

/** DS-API-003 商品詳細 */
export interface ProductDetail {
  id: number;
  name: string;
  description: string;
  material: string;
  price_incl_tax: number;
  images: string[];
  colors: string[];
  sizes: string[];
  variants: Variant[];
  related: RelatedProduct[];
}

// ---- P2-a: 商品検索・検索サジェスト（DS-API-004・004a） ----

export interface RecommendedCategory {
  slug: string;
  name: string;
  product_count: number;
}

/** DS-API-004 検索結果。`similar_keywords`・`recommended_categories` は 0 件のときだけ中身がある */
export interface SearchResponse {
  query: string;
  items: ProductSummary[];
  page: number;
  per_page: number;
  total: number;
  has_more: boolean;
  similar_keywords: string[];
  recommended_categories: RecommendedCategory[];
}

export interface SuggestItem {
  id: number;
  name: string;
}

/** DS-API-004a 検索サジェスト。最大 5 件 */
export interface SuggestResponse {
  items: SuggestItem[];
}

export interface PublicSettings {
  tax_rate: string;
  shipping_fee: number;
  free_shipping_threshold: number;
}

// ---- P2-a: コンテンツ・お知らせ・FAQ・静的ページ（DS-API-005・006） ----

export type ContentKind = "feature" | "news" | "faq" | "static";

/** DS-API-005 一覧の 1 件（body は含まない） */
export interface ContentListItem {
  slug: string;
  title: string;
  kind: ContentKind;
  /** ISO 8601（UTC）。表示は JST に変換する（DS-DEC-40） */
  publish_from: string;
}

export interface ContentsResponse {
  items: ContentListItem[];
}

/** DS-API-006 FAQ・静的ページの詳細 */
export interface ContentDetail {
  slug: string;
  kind: ContentKind;
  title: string;
  body: string;
}

export type StockStatus = "ok" | "insufficient" | "out_of_stock";

export interface CartItem {
  item_id: number;
  variant_id: number;
  product_id: number;
  product_name: string;
  color: string;
  size: string;
  unit_price: number;
  quantity: number;
  line_total: number;
  stock_status: StockStatus;
  image_path: string | null;
}

/** DS-API-010〜013 共通のカート応答 */
export interface Cart {
  cart_token: string;
  items: CartItem[];
  item_count: number;
  subtotal: number;
  shipping_fee: number;
  total: number;
  free_shipping_threshold: number;
  can_checkout: boolean;
}

/** BFF が返すエラー本文（設計仕様書 4.5）。`code` 以外は許可された詳細キーのみ */
export interface ApiErrorBody {
  code: string;
  field?: string;
  limit?: number;
  items?: unknown[];
  message?: string;
  [key: string]: unknown;
}

/** 1 明細の数量上限（DS-PRC-011）。セレクトの選択肢に使う */
export const MAX_QUANTITY_PER_ITEM = 10;

// ---- Wave 2: 注文（DS-API-021〜023。openapi.json の PrepareOut / OrderCreateIn / OrderOut と突き合わせ済み） ----

/** DS-API-021 `POST /checkout/prepare` の応答。items はカート明細と同じ形 */
export interface PrepareResponse {
  /** 注文確定に 1 回だけ使う 43 文字の base64url */
  idempotency_key: string;
  items: CartItem[];
  subtotal: number;
  shipping_fee: number;
  total: number;
  /** うち消費税（合計 × 税率 ÷（1＋税率）、円未満切り捨て） */
  tax_included: number;
  /** `"0.10"` のような文字列 */
  tax_rate: string;
  free_shipping_threshold: number;
}

/** DS-API-022 `POST /orders` の本文 */
export interface OrderCreateBody {
  idempotency_key: string;
  ship_name: string;
  /** ハイフン除去後の 7 桁 */
  ship_postal_code: string;
  /** 都道府県・市区町村・番地・建物を全角スペースで結合 */
  ship_address: string;
  /** ハイフン除去後の 10〜11 桁 */
  ship_phone: string;
  guest_email: string;
  receive_method: "delivery";
  payment_method: "card";
  /** 確認画面に表示した金額（FastAPI が再計算と照合する） */
  display: { subtotal: number; shipping_fee: number; total: number };
}

export type OrderStatus =
  | "pending_payment"
  | "accepted"
  | "preparing"
  | "shipped"
  | "delivered"
  | "pickup_expired"
  | "cancelled"
  | "payment_failed";

export interface OrderItem {
  product_name: string;
  color: string;
  size: string;
  unit_price: number;
  quantity: number;
  line_total: number;
}

/** DS-API-022／023 共通の注文応答。内部 ID は含まれない */
export interface OrderResponse {
  order_number: string;
  status: OrderStatus;
  items: OrderItem[];
  subtotal: number;
  shipping_fee: number;
  total: number;
  tax_included: number;
  tax_rate: string;
  ship_name: string;
  ship_postal_code: string;
  ship_address: string;
  ship_phone: string;
  guest_email: string;
  receive_method: string;
  payment_method: string;
  /** ISO 8601（UTC）。表示は JST に変換する */
  ordered_at: string;
}
