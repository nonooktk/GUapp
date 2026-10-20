/**
 * 管理 API（FastAPI `/api/v1/admin/*`）の応答型と、管理画面の共通定数。設計仕様書 P2 追補c 4 章を写したもの。
 * `apps/api/openapi.json` と食い違いが見つかったらここを直す（C-1 のマージ後に契約を再確認する）。
 * 内部 ID・パスワード・受け取りコードは API が返さない。`product_id`・`variant_id` だけは管理者向けの宛先として返る。
 */

/** `proxy.ts` が `/admin` 配下のリクエストにだけ付けるヘッダ（DS-DEC-122）。ルートレイアウトが読んで顧客向けの枠を省く */
export const ADMIN_AREA_HEADER = "x-admin-area";
export const ADMIN_LOGIN_PATH = "/admin/login";
export const ADMIN_HOME_PATH = "/admin/products";
/** 変更系の操作中にセッションが切れた（401 `unauthorized`）ときの移動先 */
export const ADMIN_LOGIN_EXPIRED_PATH = "/admin/login?expired=1";

/** `/admin`（と `/admin/…`）のパスか。`/administrator` のような別のパスは含めない */
export function isAdminPath(pathname: string): boolean {
  return pathname === "/admin" || pathname.startsWith("/admin/");
}

export interface AdminMe {
  login_id: string;
  role: string;
}

export interface AdminPage<T> {
  items: T[];
  page: number;
  per_page: number;
  total: number;
  has_more: boolean;
}

// ---- 商品・在庫（DS-API-051・051a・051b・051c） ----

export interface AdminProductListItem {
  product_id: number;
  name: string;
  price_incl_tax: number;
  published: boolean;
  variant_count: number;
  total_stock: number;
  out_of_stock_variants: number;
}

export interface AdminVariant {
  variant_id: number;
  sku: string;
  color: string;
  size: string;
  stock: number;
  /** 未通知の再入荷申込の件数だけ（メールアドレスは返らない） */
  restock_waiting: number;
}

export interface AdminProductDetail {
  product_id: number;
  name: string;
  price_incl_tax: number;
  published: boolean;
  updated_at: string;
  variants: AdminVariant[];
}

export interface AdminProductUpdateResult {
  product_id: number;
  published: boolean;
  price_incl_tax: number;
  changed: boolean;
  updated_at: string;
}

export interface AdminStockUpdateResult {
  variant_id: number;
  sku: string;
  stock: number;
  previous_stock: number;
  changed: boolean;
  restock_waiting: number;
}

// ---- 設定（DS-API-052・052a） ----

export type AdminSettingKey = "tax_rate" | "shipping_fee" | "free_shipping_threshold" | "payment_timeout_minutes";

export interface AdminSettingItem {
  key: AdminSettingKey;
  label: string;
  /** `tax_rate` は `"0.10"` の文字列、ほかは整数 */
  value: string | number;
  editable: boolean;
  unit: string | null;
  min: string | number | null;
  max: string | number | null;
}

export interface AdminSettingsResponse {
  items: AdminSettingItem[];
}

export interface AdminSettingsUpdateResult {
  items: AdminSettingItem[];
  changed: string[];
}

// ---- 注文（DS-API-053・053a・053b） ----

export type AdminOrderStatus =
  | "pending_payment"
  | "accepted"
  | "preparing"
  | "shipped"
  | "delivered"
  | "pickup_expired"
  | "cancelled"
  | "payment_failed";

/** 注文一覧の「状態」絞り込みの選択肢（API の列挙 8 値。表示名は受け取り方法に依らない中立の名前） */
export const ADMIN_ORDER_STATUS_OPTIONS: readonly { value: AdminOrderStatus; label: string }[] = [
  { value: "pending_payment", label: "決済待ち" },
  { value: "accepted", label: "受付済" },
  { value: "preparing", label: "出荷準備中" },
  { value: "shipped", label: "出荷済" },
  { value: "delivered", label: "配達完了" },
  { value: "pickup_expired", label: "受取期限切れ" },
  { value: "cancelled", label: "キャンセル済" },
  { value: "payment_failed", label: "決済失敗" },
];

export type AdminReceiveMethod = "delivery" | "store";

export const ADMIN_RECEIVE_METHOD_LABELS: Record<AdminReceiveMethod, string> = {
  delivery: "配送",
  store: "店舗受け取り",
};

export interface AdminOrderListItem {
  order_number: string;
  ordered_at: string;
  status: AdminOrderStatus;
  status_label: string;
  receive_method: AdminReceiveMethod;
  total: number;
  item_count: number;
  customer_type: "member" | "guest";
  /** `t***@example.com` の形 */
  email_masked: string;
}

export interface AdminTransition {
  status: string;
  label: string;
  accepts_tracking_number: boolean;
}

export interface AdminOrderDetail {
  order_number: string;
  ordered_at: string;
  status: AdminOrderStatus;
  status_label: string;
  receive_method: AdminReceiveMethod;
  store: { name: string; prefecture: string; address: string } | null;
  items: { product_name: string; color: string; size: string; unit_price: number; quantity: number }[];
  subtotal: number;
  shipping_fee: number;
  discount: number;
  total: number;
  tax_included: number;
  tax_rate: string;
  payment: { provider: string; result: string } | null;
  customer: {
    type: "member" | "guest";
    name: string;
    email_masked: string;
    /** 末尾 4 桁以外は `*` */
    phone_masked: string;
    /** 配送のときだけ */
    postal_code?: string;
    address?: string;
  };
  tracking_number: string | null;
  available_transitions: AdminTransition[];
}

export interface AdminStatusUpdateResult {
  order_number: string;
  status: AdminOrderStatus;
  status_label: string;
  tracking_number: string | null;
  available_transitions: AdminTransition[];
}
