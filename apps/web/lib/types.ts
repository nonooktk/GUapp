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

export interface PublicSettings {
  tax_rate: string;
  shipping_fee: number;
  free_shipping_threshold: number;
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
