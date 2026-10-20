import "server-only";

import {
  buildCsrfTokenCookie,
  buildSessionCookie,
  buildSessionDeleteCookie,
  readSessionToken,
  SESSION_TOKEN_HEADER,
  SESSION_TOKEN_SHAPE,
} from "@/lib/cookie";
import { apiFetch, UpstreamUnavailableError } from "@/lib/server/api";
import { generateCsrfToken } from "@/lib/server/csrf";
import { getEnv } from "@/lib/server/env";
import { clientIp, FORWARDED_FOR_HEADER } from "@/lib/server/order-proxy";

/**
 * 認証系 BFF の共通取り次ぎ（DS-API-030〜035・007。設計仕様書 3.1・4.0・4.7・7.3、テスト UT-WEB-26・IT-BFF-030a〜f・031・007）。
 *
 * - CSRF 検証・本文 8KB 上限・本文の白リスト化は各 Route Handler が先頭で行う（verifyCsrf／readJsonBody／validationError）。ここには置かない
 * - `X-Forwarded-For` に利用者の送信元 IP を載せる（`order-proxy.ts` の `clientIp` と同じ。利用者が送った値は転送しない）。
 *   FastAPI のログイン制限（IP 単位）・個別の回数制限がこの値で数える
 * - mode:
 *     "login"  : Cookie `sid` があれば `X-Session-Token` に載せる（古いセッションの削除に使う）。成功したら応答の `session_token` を
 *                Cookie `sid` にし、本文から除く。`csrf_token` を発行し直す。失敗時は `Set-Cookie` を出さない
 *     "logout" : `X-Session-Token` に `sid` を載せる。成功・失敗・接続不可のどれでも `sid` の削除 Cookie と新しい `csrf_token` を返す。成功は 204
 *     "plain"  : 登録・確認・再設定・再入荷。`forwardSession` が真なら有効な `sid` を `X-Session-Token` に載せる
 * - ブラウザへ返す本文から `session_token`・`cart_token` は除く（S4。DS-DEC-60）
 * - FastAPI のエラーは sanitizeErrorBody 済みの `{code, ...}` をそのまま返す。429 の `Retry-After` は数字のときだけ透過する
 * - 接続不可は 503 `{code:"upstream_unavailable"}`。メール・パスワード・トークンなど本文はログに書かない（path と理由だけ）
 */

export type AuthProxyMode = "login" | "logout" | "plain";

export interface AuthProxyInit {
  json?: unknown;
  mode?: AuthProxyMode;
  /** mode="plain" のとき有効な `sid` を `X-Session-Token` に載せる（再入荷の申込で member_id を記録するため） */
  forwardSession?: boolean;
}

/** 応答本文の最上位から `session_token`・`cart_token` を除く（ブラウザへ返さない値） */
export function stripSessionSecrets<T>(data: T): T {
  if (typeof data !== "object" || data === null || Array.isArray(data)) return data;
  if (!("session_token" in data) && !("cart_token" in data)) return data;
  const { session_token: _s, cart_token: _c, ...rest } = data as Record<string, unknown>;
  void _s;
  void _c;
  return rest as T;
}

function csrfReissueCookie(): string {
  const env = getEnv();
  return buildCsrfTokenCookie(generateCsrfToken(), env.APP_ENV, env.SESSION_COOKIE_DOMAIN);
}

function respond(body: unknown, status: number, headers: Headers): Response {
  if (status === 204 || status === 205 || status === 304) return new Response(null, { status, headers });
  return Response.json(body, { status, headers });
}

export async function proxyAuthRequest(request: Request, path: string, init: AuthProxyInit = {}): Promise<Response> {
  const mode = init.mode ?? "plain";
  const sid = mode === "plain" && !init.forwardSession ? null : readSessionToken(request.headers.get("cookie"));
  const headers = new Headers({ "Cache-Control": "no-store" });
  const env = getEnv();

  // ログアウトは結果にかかわらずブラウザ側の `sid` を消し、`csrf_token` を発行し直す
  const clearSession = () => {
    headers.append("Set-Cookie", buildSessionDeleteCookie(env.APP_ENV, env.SESSION_COOKIE_DOMAIN));
    headers.append("Set-Cookie", csrfReissueCookie());
  };

  let result;
  try {
    result = await apiFetch<unknown>(path, {
      method: "POST",
      json: init.json,
      headers: { [FORWARDED_FOR_HEADER]: clientIp(request), ...(sid ? { [SESSION_TOKEN_HEADER]: sid } : {}) },
      // argon2id の検証・ハッシュ化（同時 2 本まで）を待つことがあるため、カート系より長めに待つ
      timeoutMs: 15000,
    });
  } catch (err) {
    if (mode === "logout") clearSession();
    if (err instanceof UpstreamUnavailableError) {
      return Response.json({ code: "upstream_unavailable" }, { status: 503, headers });
    }
    console.error("[api/auth] unexpected error", { path, reason: err instanceof Error ? err.message : String(err) });
    return Response.json({ code: "internal_error", message: "処理中にエラーが発生しました" }, { status: 500, headers });
  }

  if (mode === "logout") clearSession();

  if (!result.ok) {
    if (result.status === 429 && result.retryAfter && /^[0-9]{1,6}$/.test(result.retryAfter)) {
      headers.set("Retry-After", result.retryAfter);
    }
    return Response.json(result.error, { status: result.status, headers });
  }

  if (mode === "login") {
    const data = result.data;
    const token = typeof data === "object" && data !== null ? (data as { session_token?: unknown }).session_token : undefined;
    if (typeof token !== "string" || !SESSION_TOKEN_SHAPE.test(token)) {
      // 契約違反（トークンが無い・形が違う）。Cookie は発行しない
      console.error("[api/auth] login response without a valid session_token", { path });
      return Response.json({ code: "upstream_error" }, { status: 502, headers });
    }
    headers.append("Set-Cookie", buildSessionCookie(token, env.APP_ENV, env.SESSION_COOKIE_DOMAIN));
    headers.append("Set-Cookie", csrfReissueCookie());
  }

  return respond(stripSessionSecrets(result.data), result.status, headers);
}

export interface PickResult {
  payload: Record<string, unknown>;
  fields: { name: string; reason: string }[];
}

/**
 * 本文の白リスト化（mass assignment 対策。A-03）。`required` は文字列必須（無い・文字列でない → `required`）。
 * `optionalStrings`／`optionalBooleans` は無い・null なら落とし、型が違えば `format`。これ以外のキーは FastAPI へ渡さない。
 */
export function pickBody(
  body: Record<string, unknown>,
  spec: { required: readonly string[]; optionalStrings?: readonly string[]; optionalBooleans?: readonly string[] },
): PickResult {
  const payload: Record<string, unknown> = {};
  const fields: PickResult["fields"] = [];
  for (const key of spec.required) {
    const v = body[key];
    if (typeof v === "string") payload[key] = v;
    else fields.push({ name: key, reason: "required" });
  }
  for (const key of spec.optionalStrings ?? []) {
    const v = body[key];
    if (v === undefined || v === null) continue;
    if (typeof v === "string") payload[key] = v;
    else fields.push({ name: key, reason: "format" });
  }
  for (const key of spec.optionalBooleans ?? []) {
    const v = body[key];
    if (v === undefined || v === null) continue;
    if (typeof v === "boolean") payload[key] = v;
    else fields.push({ name: key, reason: "format" });
  }
  return { payload, fields };
}
