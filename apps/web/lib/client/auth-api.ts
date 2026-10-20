import { CSRF_HEADER } from "@/lib/csrf-validation";
import { CartApiError, ensureCsrfToken } from "@/lib/client/cart-api";
import { OrderApiError, post } from "@/lib/client/order-api";
import type { ApiErrorBody } from "@/lib/types";

/**
 * ブラウザから認証系 BFF（`/api/auth/*`）を呼ぶ薄いクライアント（設計仕様書 4.7）。
 * - すべて POST なので `X-CSRF-Token` を載せる（order-api の post が ensureCsrfToken で用意する）
 * - 失敗は OrderApiError（CartApiError を継承。status と `{code,...}` 本文・429 の retryAfterSec）で投げる。文言化は lib/auth-messages.ts
 * - ログイン・ログアウトの成功時は BFF が `csrf_token` を発行し直す。次の呼び出しは `document.cookie` の新しい値を読む
 */

export interface LoginResult {
  member: { name: string; email_verified: boolean };
}

export async function login(email: string, password: string): Promise<LoginResult> {
  return (await post<LoginResult>("/api/auth/login", { email, password })).data;
}

export interface RegisterInput {
  email: string;
  password: string;
  name: string;
  birth_date?: string;
  gender?: string;
  personalize_opt_in?: boolean;
}

/** 202 `{status:"accepted"}`。新規・既登録で同じ（DS-DEC-71） */
export async function register(input: RegisterInput): Promise<void> {
  await post<{ status: string }>("/api/auth/register", input);
}

/**
 * 204（本文なし）。失敗したときも BFF は `sid` の削除 Cookie を返す（ブラウザ側はログアウト済みになる）ので、
 * 呼び出し側は失敗でも `router.refresh()` する。2xx 以外は OrderApiError。
 */
export async function logout(): Promise<void> {
  const csrf = await ensureCsrfToken();
  const res = await fetch("/api/auth/logout", {
    method: "POST",
    headers: { [CSRF_HEADER]: csrf, Accept: "application/json" },
    credentials: "same-origin",
    cache: "no-store",
  });
  if (res.ok) return;
  let body: ApiErrorBody | null = null;
  try {
    body = (await res.json()) as ApiErrorBody;
  } catch {
    body = null;
  }
  throw new OrderApiError(res.status, body);
}

export async function verifyEmail(token: string): Promise<void> {
  await post<{ verified: boolean }>("/api/auth/verify-email", { token });
}

export async function requestPasswordReset(email: string): Promise<void> {
  await post<{ status: string }>("/api/auth/password-reset/request", { email });
}

export async function confirmPasswordReset(token: string, password: string): Promise<void> {
  await post<{ status: string }>("/api/auth/password-reset/confirm", { token, password });
}

/** 失敗の status と本文を取り出す（CartApiError 以外＝ネットワーク断などは 0／null） */
export function errorParts(err: unknown): { status: number; body: ApiErrorBody | null } {
  return err instanceof CartApiError ? { status: err.status, body: err.body } : { status: 0, body: null };
}
