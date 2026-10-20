import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE, SESSION_TOKEN_HEADER, SESSION_TOKEN_SHAPE } from "@/lib/cookie";
import { apiFetch, UpstreamUnavailableError, type ApiResult } from "@/lib/server/api";
import type { MemberInfo, OrderHistoryResponse, OrderResponse } from "@/lib/types";

/**
 * 会員向けデータの取得（Server Component から FastAPI を直接呼ぶ。設計仕様書 1 章・4.7）。
 * - Cookie `sid` を `X-Session-Token` に載せる（値は解釈しない。形が違う値は「セッションなし」）
 * - `/me` 系が 401（セッション無し・不明・期限切れ・匿名化済み）のとき `redirect("/login?next=/mypage")`
 * - 404 は呼び出し側が `notFound()` にする（他人の注文・ゲスト注文・不存在・形の不正を区別しない）
 * - `redirect()` は例外で制御を戻すため、try/catch の外で呼ぶ
 * - 全て `cache: "no-store"`（apiFetch 内で固定）。ページ側は cookies() を読むので動的描画になる
 */

export const LOGIN_REDIRECT_PATH = "/login?next=/mypage";

/** ヘッダー用: Cookie `sid` があるか。FastAPI は呼ばない（全ページで DB を引かない。DS-DEC-86） */
export async function hasSessionCookie(): Promise<boolean> {
  const store = await cookies();
  return store.has(SESSION_COOKIE);
}

async function sessionTokenFromCookies(): Promise<string | null> {
  const store = await cookies();
  const v = store.get(SESSION_COOKIE)?.value ?? null;
  return v !== null && SESSION_TOKEN_SHAPE.test(v) ? v : null;
}

export type MemberLoad<T> = { kind: "ok"; data: T } | { kind: "not_found" } | { kind: "error" };

/**
 * `/me` 系の GET。`sid` が無い・401 のときは `/login?next=/mypage` へ redirect（戻らない）。
 * 接続不可・その他の失敗は `{kind:"error"}`、404 は `{kind:"not_found"}`。
 */
export async function loadMemberData<T>(path: string): Promise<MemberLoad<T>> {
  const sid = await sessionTokenFromCookies();
  if (!sid) redirect(LOGIN_REDIRECT_PATH);

  let result: ApiResult<T>;
  try {
    result = await apiFetch<T>(path, { headers: { [SESSION_TOKEN_HEADER]: sid } });
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) return { kind: "error" };
    throw err;
  }
  if (!result.ok) {
    if (result.status === 401) redirect(LOGIN_REDIRECT_PATH);
    if (result.status === 404) return { kind: "not_found" };
    console.error("[member] request failed", { path: path.split("?")[0], status: result.status, code: result.error.code });
    return { kind: "error" };
  }
  return { kind: "ok", data: result.data };
}

export function loadMe(): Promise<MemberLoad<MemberInfo>> {
  return loadMemberData<MemberInfo>("/me");
}

export function loadMyOrders(page: number, perPage = 10): Promise<MemberLoad<OrderHistoryResponse>> {
  return loadMemberData<OrderHistoryResponse>(`/me/orders?page=${page}&per_page=${perPage}`);
}

export function loadMyOrder(orderNumber: string): Promise<MemberLoad<OrderResponse>> {
  return loadMemberData<OrderResponse>(`/me/orders/${encodeURIComponent(orderNumber)}`);
}

/**
 * ログイン中なら会員情報、そうでなければ null（redirect しない）。
 * `/checkout`（氏名・メールの初期値）と `/login`（ログイン済みか）で使う。
 * `sid` が無い・失効・接続不可はどれも null（注文手続きはゲストとして続けられる）。
 */
export async function getMemberOrNull(): Promise<MemberInfo | null> {
  const sid = await sessionTokenFromCookies();
  if (!sid) return null;
  try {
    const result = await apiFetch<MemberInfo>("/me", { headers: { [SESSION_TOKEN_HEADER]: sid } });
    return result.ok ? result.data : null;
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) return null;
    throw err;
  }
}
