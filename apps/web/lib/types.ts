/**
 * FastAPI（`/api/v1`）の応答型。Wave 1 の API 契約（コーディネーター指示・設計仕様書 4.2）を写したもの。
 * `apps/api/openapi.json` と食い違いが見つかったらここを直す。
 */

export type Gender = "women" | "men" | "kids_teen" | "all";

export interface CategoryChild {
  slug: string;
  name: string;
  /** 種類（tops など）。性別をまたいで同じ種類を束ねる軸。`/products?kind=` に渡す */
  kind: string | null;
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
  /** P2-b（DS-API-003・DS-PRC-003a）。レビューが 0 件でもキーは出る。件数のみで割合は返さない */
  fit_summary: FitSummary;
}

/** サイズ感の集計（承認済みで `fit` が回答されたレビューの件数）。`total = small + just + large` */
export interface FitSummary {
  total: number;
  small: number;
  just: number;
  large: number;
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

/**
 * DS-API-010〜013 共通のカート応答（ブラウザへ返す形）。
 * `cart_token` は含めない（S4）。FastAPI の応答には入っているが、BFF が Cookie に移して本文から除く。
 * BFF 内部の型は lib/server/cart-proxy.ts の `UpstreamCart`。
 */
export interface Cart {
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
  /** P2-b: 受け取り方法（`store` のとき送料 0）。古い応答には無い */
  receive_method?: ReceiveMethod;
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

/** 受け取り方法（DS-API-021・022） */
export type ReceiveMethod = "delivery" | "store";

/** DS-API-022 `POST /orders` の本文。`receive_method=store` では `ship_postal_code`・`ship_address` を送らず `store_code` を送る */
export interface OrderCreateBody {
  idempotency_key: string;
  ship_name: string;
  /** ハイフン除去後の 7 桁（配送のみ） */
  ship_postal_code?: string;
  /** 都道府県・市区町村・番地・建物を全角スペースで結合（配送のみ） */
  ship_address?: string;
  /** ハイフン除去後の 10〜11 桁 */
  ship_phone: string;
  /** 店舗受け取りでは受け取る方の連絡先メール（会員の注文でも項目名は変わらない） */
  guest_email: string;
  receive_method: ReceiveMethod;
  /** 店舗受け取りのみ（`^[a-z0-9-]{1,32}$`） */
  store_code?: string;
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

/** 注文の受け取り店舗（内部 ID・郵便番号は含まれない） */
export interface OrderStore {
  name: string;
  prefecture: string;
  address: string;
}

/** DS-API-022／023／024a 共通の注文応答。内部 ID は含まれない */
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
  /** P2-b（4.4）: `store` のときだけ。それ以外は null。古い応答（sessionStorage の保存分）には無い */
  store?: OrderStore | null;
  /** 8 文字（区切りなし）。`store` かつ状態が accepted・preparing・shipped のときだけ値が入る */
  pickup_code?: string | null;
  /** `delivery` で shipped・delivered かつ登録済みのときだけ */
  tracking_number?: string | null;
  /** 受付から受け取り可能までの区分の表示名（DS-PRC-024a） */
  status_label?: string;
  /** 注文に会員が紐づいているか。完了画面の案内の出し分けに使う */
  is_member_order?: boolean;
}

// ---- P2-b: 会員・注文履歴・店舗（DS-API-036・024・024a・026） ----

/** DS-API-036 `GET /me`。内部 ID・生年月日・性別は返らない */
export interface MemberInfo {
  name: string;
  email: string;
  email_verified: boolean;
  personalize_opt_in: boolean;
}

/** DS-API-024 一覧の 1 件 */
export interface OrderHistoryItem {
  order_number: string;
  status: OrderStatus;
  status_label: string;
  /** ISO 8601（UTC） */
  ordered_at: string;
  total: number;
  receive_method: string;
  /** 数量の合計 */
  item_count: number;
  first_item_name: string;
}

export interface OrderHistoryResponse {
  items: OrderHistoryItem[];
  page: number;
  per_page: number;
  total: number;
  has_more: boolean;
}

/** DS-API-026 受け取り店舗の 1 件。郵便番号・内部 ID は返らない */
export interface StoreSummary {
  code: string;
  name: string;
  prefecture: string;
  address: string;
}

export interface StoresResponse {
  items: StoreSummary[];
}
