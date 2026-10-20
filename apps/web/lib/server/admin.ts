import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ADMIN_SESSION_COOKIE, ADMIN_SESSION_TOKEN_HEADER, isAdminSessionTokenShape } from "@/lib/admin-cookie";
import {
  ADMIN_LOGIN_PATH,
  type AdminMe,
  type AdminOrderDetail,
  type AdminOrderListItem,
  type AdminPage,
  type AdminProductDetail,
  type AdminProductListItem,
  type AdminSettingsResponse,
} from "@/lib/admin-types";
import { apiFetch, UpstreamUnavailableError, type ApiError, type ApiResult } from "@/lib/server/api";

/**
 * 管理データの取得（Server Component から FastAPI の管理 API を直接呼ぶ。設計仕様書 P2 追補c 1 章 3・4.5、テスト UT-WEB-51）。
 * - Cookie `asid` を `X-Admin-Session-Token` に載せる（値は解釈しない。形が違う値は「セッションなし」）。会員の `sid` は渡さない
 * - `asid` が無い、または 401・403 のときは `redirect("/admin/login")`（内容は一切表示しない。要件定義書 5.3 異常系）
 * - 404 は呼び出し側が `notFound()` にする。500・接続不可は `{kind:"error"}`（呼び出し側が `LoadError` を出す）
 * - `redirect()` は例外で制御を戻すため、try/catch の外で呼ぶ
 * - 全て `cache: "no-store"`（apiFetch 内で固定）。ページ側は cookies() を読むので動的描画になる
 * - ログには path（クエリなし・注文番号は伏せる）と status・code だけを書く。メール・氏名など検索語や個人情報は書かない
 */

export type AdminLoad<T> =
  | { kind: "ok"; data: T }
  | { kind: "not_found" }
  | { kind: "error"; status: number; body: ApiError | null };

async function adminTokenFromCookies(): Promise<string | null> {
  const store = await cookies();
  const v = store.get(ADMIN_SESSION_COOKIE)?.value ?? null;
  return isAdminSessionTokenShape(v) ? v : null;
}

function logPath(path: string): string {
  return path.split("?")[0].replace(/GU-\d{6}-[0-9A-Za-z]{4,16}/g, ":order_number").slice(0, 120);
}

/**
 * 管理 API の GET。`asid` が無い・401・403 のときは `/admin/login` へ redirect（戻らない）。
 * `path` は `/admin/…` から始まる FastAPI のパス（`/api/v1` は apiFetch が付ける）。
 */
export async function loadAdminData<T>(path: string): Promise<AdminLoad<T>> {
  const asid = await adminTokenFromCookies();
  if (!asid) redirect(ADMIN_LOGIN_PATH);

  let result: ApiResult<T>;
  try {
    result = await apiFetch<T>(path, { headers: { [ADMIN_SESSION_TOKEN_HEADER]: asid } });
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) return { kind: "error", status: 503, body: { code: "upstream_unavailable" } };
    throw err;
  }
  if (!result.ok) {
    if (result.status === 401 || result.status === 403) redirect(ADMIN_LOGIN_PATH);
    if (result.status === 404) return { kind: "not_found" };
    console.error("[admin] request failed", { path: logPath(path), status: result.status, code: result.error.code });
    return { kind: "error", status: result.status, body: result.error };
  }
  return { kind: "ok", data: result.data };
}

/**
 * ログイン中の管理者、そうでなければ null（redirect しない）。
 * `/admin` のレイアウト（シェルを出すか）と `/admin/login`（ログイン済みか）で使う。
 * `asid` が無い・失効・接続不可はどれも null。
 */
export async function getAdminOrNull(): Promise<AdminMe | null> {
  const asid = await adminTokenFromCookies();
  if (!asid) return null;
  try {
    const result = await apiFetch<AdminMe>("/admin/me", { headers: { [ADMIN_SESSION_TOKEN_HEADER]: asid } });
    return result.ok ? result.data : null;
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) return null;
    throw err;
  }
}

/**
 * 管理者であることだけを確認する（`GET /admin/me`）。未ログイン・失効・会員のセッションは `/admin/login` へ redirect（戻らない）。
 * FastAPI にデータを取りに行かないページ（検索条件の誤りで一覧を取らないとき）が、未ログインでも内容を出さないために呼ぶ。
 */
export async function requireAdmin(): Promise<void> {
  await loadAdminData<AdminMe>("/admin/me");
}

export function loadAdminProducts(query: string): Promise<AdminLoad<AdminPage<AdminProductListItem>>> {
  return loadAdminData(`/admin/products?${query}`);
}

export function loadAdminProduct(productId: string): Promise<AdminLoad<AdminProductDetail>> {
  return loadAdminData(`/admin/products/${encodeURIComponent(productId)}`);
}

export function loadAdminOrders(query: string): Promise<AdminLoad<AdminPage<AdminOrderListItem>>> {
  return loadAdminData(`/admin/orders?${query}`);
}

export function loadAdminOrder(orderNumber: string): Promise<AdminLoad<AdminOrderDetail>> {
  return loadAdminData(`/admin/orders/${encodeURIComponent(orderNumber)}`);
}

export function loadAdminSettings(): Promise<AdminLoad<AdminSettingsResponse>> {
  return loadAdminData("/admin/settings");
}
