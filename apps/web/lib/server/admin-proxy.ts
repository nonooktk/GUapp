import "server-only";

import {
  ADMIN_SESSION_TOKEN_HEADER,
  buildAdminSessionCookie,
  buildAdminSessionDeleteCookie,
  readAdminSessionToken,
} from "@/lib/admin-cookie";
import { SESSION_TOKEN_SHAPE, buildCsrfTokenCookie } from "@/lib/cookie";
import { apiFetch, UpstreamUnavailableError } from "@/lib/server/api";
import { stripSessionSecrets } from "@/lib/server/auth-proxy";
import { validationError } from "@/lib/server/cart-proxy";
import { generateCsrfToken } from "@/lib/server/csrf";
import { getEnv } from "@/lib/server/env";
import { clientIp, FORWARDED_FOR_HEADER } from "@/lib/server/order-proxy";

/**
 * 管理 BFF の共通取り次ぎ（設計仕様書 P2 追補c 4.5・3.1・7.3・DS-DEC-108・121・126、テスト UT-WEB-50・IT-BFF-050〜055）。
 * 既存の認証系 BFF（auth-proxy.ts）と同じ作法で、会員の `sid`・`X-Session-Token` とは別系統にする。
 *
 * - CSRF 検証・本文 8KB 上限・本文の白リスト化は各 Route Handler が先頭で行う（verifyCsrf／readJsonBody／pickAdminBody）。ここには置かない
 * - FastAPI へ渡すヘッダは `X-Admin-Session-Token`（Cookie `asid` の値）と `X-Forwarded-For`（利用者の送信元 IP。利用者が送った値は転送しない）だけ。
 *   会員の `sid`・`cart_token` は渡さない
 * - mode:
 *     "login"  : `asid` があれば `X-Admin-Session-Token` に載せる（古いセッションの削除に使う）。成功したら応答の `session_token` を
 *                Cookie `asid`（Path=/admin・SameSite=Strict）にし、本文から除く。`csrf_token` を発行し直す。失敗時は `Set-Cookie` を出さない
 *     "logout" : `asid` があれば `X-Admin-Session-Token` に載せる。成功・失敗・接続不可のどれでも `asid` の削除 Cookie と新しい `csrf_token` を返す。成功は 204
 *     "update" : 商品・在庫・設定・注文状態の変更。`asid` が無い・形が違うときは FastAPI を呼ばずに 401 `unauthorized`
 * - FastAPI のエラーは sanitizeErrorBody 済みの `{code, ...}`（`current` を含む）をそのまま返す。429 の `Retry-After` は数字のときだけ透過する
 * - 接続不可は 503 `upstream_unavailable`。パスワード・トークン・本文は、応答にもログにも書かない（path と理由だけ）
 */

export type AdminProxyMode = "login" | "logout" | "update";

export interface AdminProxyInit {
  mode: AdminProxyMode;
  method?: "POST" | "PATCH";
  json?: unknown;
}

function csrfReissueCookie(): string {
  const env = getEnv();
  return buildCsrfTokenCookie(generateCsrfToken(), env.APP_ENV, env.SESSION_COOKIE_DOMAIN);
}

function respond(body: unknown, status: number, headers: Headers): Response {
  if (status === 204 || status === 205 || status === 304) return new Response(null, { status, headers });
  return Response.json(body, { status, headers });
}

export async function proxyAdminRequest(request: Request, path: string, init: AdminProxyInit): Promise<Response> {
  const { mode } = init;
  const asid = readAdminSessionToken(request.headers.get("cookie"));
  const headers = new Headers({ "Cache-Control": "no-store" });
  const env = getEnv();

  if (mode === "update" && !asid) {
    return Response.json({ code: "unauthorized" }, { status: 401, headers });
  }

  // ログアウトは結果にかかわらずブラウザ側の `asid` を消し、`csrf_token` を発行し直す
  const clearSession = () => {
    headers.append("Set-Cookie", buildAdminSessionDeleteCookie(env.APP_ENV, env.SESSION_COOKIE_DOMAIN));
    headers.append("Set-Cookie", csrfReissueCookie());
  };

  // `asid` が無いログアウトは、消す対象も FastAPI で消す行も無い（冪等）。FastAPI は呼ばない
  if (mode === "logout" && !asid) {
    clearSession();
    return respond(null, 204, headers);
  }

  let result;
  try {
    result = await apiFetch<unknown>(path, {
      method: init.method ?? (mode === "update" ? "PATCH" : "POST"),
      json: init.json,
      headers: { [FORWARDED_FOR_HEADER]: clientIp(request), ...(asid ? { [ADMIN_SESSION_TOKEN_HEADER]: asid } : {}) },
      // ログインは argon2id の検証（同時 2 本まで）を待つことがあるため、更新系より長めに待つ
      timeoutMs: mode === "login" ? 15000 : 10000,
    });
  } catch (err) {
    if (mode === "logout") clearSession();
    if (err instanceof UpstreamUnavailableError) {
      return Response.json({ code: "upstream_unavailable" }, { status: 503, headers });
    }
    console.error("[admin/api] unexpected error", { path, reason: err instanceof Error ? err.message : String(err) });
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
      console.error("[admin/api] login response without a valid session_token", { path });
      return Response.json({ code: "upstream_error" }, { status: 502, headers });
    }
    headers.append("Set-Cookie", buildAdminSessionCookie(token, env.APP_ENV, env.SESSION_COOKIE_DOMAIN));
    headers.append("Set-Cookie", csrfReissueCookie());
  }

  return respond(stripSessionSecrets(result.data), result.status, headers);
}

// ---- 本文の白リスト化（mass assignment 対策。A-03） ----

export type AdminFieldType = "string" | "int" | "boolean";

export interface AdminBodySpec {
  /** 項目名 → 型。ここに無いキー（`name`・`role`・`member_id` など）は FastAPI へ渡さない */
  fields: Record<string, AdminFieldType>;
  /** 無い・null のとき 400 `required` にする項目 */
  required?: readonly string[];
}

export interface AdminPickResult {
  payload: Record<string, unknown>;
  fields: { name: string; reason: string }[];
}

/**
 * 型を検査しながら白リストの項目だけを拾う。型が違えば 400 `format`、必須の欠落は `required`（どちらも FastAPI を呼ばない）。
 * 整数は JavaScript で正確に扱える範囲（`Number.isSafeInteger`）のものだけ。業務の範囲と 2,147,483,647 を超える桁あふれの判定は FastAPI。
 */
export function pickAdminBody(body: Record<string, unknown>, spec: AdminBodySpec): AdminPickResult {
  const payload: Record<string, unknown> = {};
  const fields: AdminPickResult["fields"] = [];
  const required = new Set(spec.required ?? []);
  for (const [key, type] of Object.entries(spec.fields)) {
    const v = body[key];
    if (v === undefined || v === null) {
      if (required.has(key)) fields.push({ name: key, reason: "required" });
      continue;
    }
    const ok =
      (type === "string" && typeof v === "string") ||
      (type === "boolean" && typeof v === "boolean") ||
      (type === "int" && typeof v === "number" && Number.isSafeInteger(v));
    if (ok) payload[key] = v;
    else fields.push({ name: key, reason: "format" });
  }
  return { payload, fields };
}

/** パスの動的区間（`[productId]` など）の検査。形が違えば 400 `validation_error`（FastAPI を呼ばない）。通れば null */
export function pathParamError(request: Request, name: string, value: string, shape: RegExp): Response | null {
  return shape.test(value) ? null : validationError(request, [{ name, reason: "format" }]);
}

/** 9223372036854775807 以下の 1 以上の整数の文字列（API のパスの範囲）。JavaScript の数値には直さず、文字列のまま FastAPI へ渡す */
export const POSITIVE_ID_PATH_SHAPE = /^[1-9][0-9]{0,18}$/;
