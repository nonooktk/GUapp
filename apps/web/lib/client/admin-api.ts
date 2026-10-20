import type {
  AdminProductUpdateResult,
  AdminSettingsUpdateResult,
  AdminStatusUpdateResult,
  AdminStockUpdateResult,
} from "@/lib/admin-types";
import { CartApiError, readCsrfCookie } from "@/lib/client/cart-api";
import { CSRF_HEADER } from "@/lib/csrf-validation";
import type { ApiErrorBody } from "@/lib/types";

/**
 * ブラウザから管理 BFF（`/admin/api/*`）を呼ぶ薄いクライアント（設計仕様書 P2 追補c 4.5・DS-DEC-121）。
 * - すべて変更系なので `X-CSRF-Token` を載せる。`csrf_token` が未発行なら先に `GET /admin/api/csrf`（204）で発行させる
 *   （管理画面は FastAPI のカートを作る `GET /api/cart` を呼ばない）
 * - 失敗は AdminApiError（status と `{code,...}` 本文・429 の retryAfterSec）で投げる。文言化は lib/admin-messages.ts
 * - ログイン・ログアウトの成功時は BFF が `csrf_token` を発行し直す。次の呼び出しは `document.cookie` の新しい値を読む
 */

export class AdminApiError extends CartApiError {
  constructor(
    status: number,
    body: ApiErrorBody | null,
    readonly retryAfterSec: number | null = null,
  ) {
    super(status, body);
    this.name = "AdminApiError";
  }
}

async function parseJson<T>(res: Response): Promise<T | null> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

/** CSRF トークンを返す。未発行なら `GET /admin/api/csrf` で発行させてから読む */
export async function ensureAdminCsrfToken(): Promise<string> {
  let token = readCsrfCookie(document.cookie);
  if (token) return token;
  const res = await fetch("/admin/api/csrf", { method: "GET", headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store" });
  if (!res.ok) throw new AdminApiError(res.status, await parseJson<ApiErrorBody>(res));
  token = readCsrfCookie(document.cookie);
  if (!token) throw new AdminApiError(403, { code: "forbidden" });
  return token;
}

async function send<T>(input: string, method: "POST" | "PATCH", json?: unknown): Promise<{ status: number; data: T | null }> {
  const csrf = await ensureAdminCsrfToken();
  const headers: Record<string, string> = { [CSRF_HEADER]: csrf, Accept: "application/json" };
  if (json !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(input, {
    method,
    headers,
    body: json !== undefined ? JSON.stringify(json) : undefined,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!res.ok) {
    const ra = res.headers.get("Retry-After");
    const sec = ra && /^\d+$/.test(ra) ? Number(ra) : null;
    throw new AdminApiError(res.status, await parseJson<ApiErrorBody>(res), sec);
  }
  return { status: res.status, data: await parseJson<T>(res) };
}

async function sendJson<T>(input: string, method: "POST" | "PATCH", json?: unknown): Promise<T> {
  const { status, data } = await send<T>(input, method, json);
  if (data === null) throw new AdminApiError(status, { code: "bad_response" });
  return data;
}

export interface AdminLoginResult {
  staff: { login_id: string; role: string };
}

/** POST /admin/api/auth/login。成功すると BFF が Cookie `asid` を発行する（本文に session_token は無い） */
export function adminLogin(loginId: string, password: string): Promise<AdminLoginResult> {
  return sendJson<AdminLoginResult>("/admin/api/auth/login", "POST", { login_id: loginId, password });
}

/**
 * POST /admin/api/auth/logout（204）。失敗したときも BFF は `asid` の削除 Cookie を返す（ブラウザ側はログアウト済みになる）ので、
 * 呼び出し側は失敗でも `/admin/login` へ移す。2xx 以外は AdminApiError。
 */
export async function adminLogout(): Promise<void> {
  await send<unknown>("/admin/api/auth/logout", "POST");
}

export interface ProductUpdateBody {
  published?: boolean;
  price_incl_tax?: number;
  expected_published?: boolean;
  expected_price_incl_tax?: number;
}

export function updateAdminProduct(productId: number, body: ProductUpdateBody): Promise<AdminProductUpdateResult> {
  return sendJson<AdminProductUpdateResult>(`/admin/api/products/${productId}`, "PATCH", body);
}

export function updateAdminStock(variantId: number, stock: number, expectedStock: number): Promise<AdminStockUpdateResult> {
  return sendJson<AdminStockUpdateResult>(`/admin/api/variants/${variantId}/stock`, "PATCH", { stock, expected_stock: expectedStock });
}

export interface SettingsUpdateBody {
  tax_rate?: string;
  shipping_fee?: number;
  free_shipping_threshold?: number;
  expected_tax_rate?: string;
  expected_shipping_fee?: number;
  expected_free_shipping_threshold?: number;
}

export function updateAdminSettings(body: SettingsUpdateBody): Promise<AdminSettingsUpdateResult> {
  return sendJson<AdminSettingsUpdateResult>("/admin/api/settings", "PATCH", body);
}

export function updateAdminOrderStatus(orderNumber: string, status: string, trackingNumber?: string): Promise<AdminStatusUpdateResult> {
  return sendJson<AdminStatusUpdateResult>(
    `/admin/api/orders/${encodeURIComponent(orderNumber)}/status`,
    "PATCH",
    trackingNumber ? { status, tracking_number: trackingNumber } : { status },
  );
}

/** 失敗の status と本文を取り出す（AdminApiError 以外＝ネットワーク断などは 0／null） */
export function adminErrorParts(err: unknown): { status: number; body: ApiErrorBody | null } {
  return err instanceof CartApiError ? { status: err.status, body: err.body } : { status: 0, body: null };
}
