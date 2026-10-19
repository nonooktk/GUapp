import "server-only";

import { buildCartTokenCookie, CART_TOKEN_COOKIE, readCookie } from "@/lib/cookie";
import { apiFetch, UpstreamUnavailableError } from "@/lib/server/api";
import { issueCsrfCookieIfMissing } from "@/lib/server/csrf";
import { getEnv } from "@/lib/server/env";
import { logRejection } from "@/lib/server/security-log";
import type { Cart } from "@/lib/types";

/**
 * カート BFF の共通取り次ぎ（DS-API-010〜013・設計仕様書 4.3・7.3）。
 * - Cookie `cart_token` を `X-Cart-Token` ヘッダに載せて FastAPI を呼ぶ（トークン発行者は FastAPI）
 * - 応答の `cart_token` が Cookie と異なる（または Cookie 無し）なら `Set-Cookie: cart_token=…`。
 *   `cart_token` が null（GET /cart でカートがまだ無い）ときは cart_token の Set-Cookie を出さない（S3）
 * - ブラウザへ返す本文から `cart_token` は除く（S4。Cookie の処理は除く前の値で行う）
 * - Cookie `csrf_token` が未発行なら同時に発行する
 * - FastAPI のエラーは sanitizeErrorBody 済みの `{code, ...}` をそのままの status で返す
 * - 接続不可は 503 `{code:"upstream_unavailable"}`
 */

export const CART_TOKEN_HEADER = "X-Cart-Token";

/** 本文の上限（S2）。カート・注文の本文はどれも数百バイトなので 8KB で十分 */
export const MAX_BODY_BYTES = 8192;

/** FastAPI のカート応答（BFF 内部用）。`cart_token` はカートがまだ無いとき null。ブラウザには返さない */
export type UpstreamCart = Cart & { cart_token: string | null };

/**
 * 応答本文から最上位の `cart_token` を除く（S4）。オブジェクト以外はそのまま返す。
 * Server Component が Client Component へ渡す props（RSC ペイロード）に載せる前にも通す。
 */
export function stripCartToken<T>(data: T): T {
  if (typeof data !== "object" || data === null || Array.isArray(data) || !("cart_token" in data)) return data;
  const { cart_token: _omitted, ...rest } = data as Record<string, unknown>;
  void _omitted;
  return rest as T;
}

export interface CartProxyInit {
  method: "GET" | "POST" | "PATCH" | "DELETE";
  json?: unknown;
}

/** `X-Cart-Token` に載せるヘッダ。Cookie が無ければ空（FastAPI が新規発行する） */
export function cartTokenHeaders(cartToken: string | null): Record<string, string> {
  return cartToken ? { [CART_TOKEN_HEADER]: cartToken } : {};
}

export async function proxyCartRequest(request: Request, path: string, init: CartProxyInit): Promise<Response> {
  const cookieHeader = request.headers.get("cookie");
  const currentToken = readCookie(cookieHeader, CART_TOKEN_COOKIE);

  let result;
  try {
    result = await apiFetch<UpstreamCart>(path, {
      method: init.method,
      json: init.json,
      headers: cartTokenHeaders(currentToken),
    });
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) {
      return Response.json({ code: "upstream_unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
    }
    console.error("[api/cart] unexpected error", err instanceof Error ? err.message : err);
    return Response.json(
      { code: "internal_error", message: "処理中にエラーが発生しました" },
      { status: 500, headers: { "Cache-Control": "no-store" } },
    );
  }

  const headers = new Headers({ "Cache-Control": "no-store" });

  if (!result.ok) {
    return Response.json(result.error, { status: result.status, headers });
  }

  const upstreamToken = result.data?.cart_token;
  const env = getEnv();
  if (typeof upstreamToken === "string" && upstreamToken !== currentToken) {
    headers.append("Set-Cookie", buildCartTokenCookie(upstreamToken, env.APP_ENV, env.SESSION_COOKIE_DOMAIN));
  }
  const csrfCookie = issueCsrfCookieIfMissing(request);
  if (csrfCookie) headers.append("Set-Cookie", csrfCookie);

  return Response.json(stripCartToken(result.data), { status: result.status, headers });
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type JsonBodyResult =
  | { ok: true; body: Record<string, unknown> | null }
  | { ok: false; response: Response };

/** 413 payload_too_large（S2）。FastAPI は呼ばない */
function payloadTooLarge(request: Request): Response {
  logRejection(request, { event: "payload_too_large", status: 413, code: "payload_too_large" });
  return Response.json({ code: "payload_too_large" }, { status: 413, headers: { "Cache-Control": "no-store" } });
}

/**
 * JSON 本文を読む（S2）。`Content-Length` が 8192 バイトを超える、または読み取った本文が 8192 バイトを超えたら
 * 413 の Response を返す（超えた時点で読み取りを打ち切る）。壊れた JSON・オブジェクト以外は `body: null`
 * （呼び出し側で 400 validation_error にする）。
 */
export async function readJsonBody(request: Request): Promise<JsonBodyResult> {
  const declared = request.headers.get("content-length");
  if (declared !== null && /^\d+$/.test(declared.trim()) && Number(declared) > MAX_BODY_BYTES) {
    return { ok: false, response: payloadTooLarge(request) };
  }

  const chunks: Uint8Array[] = [];
  let total = 0;
  if (request.body) {
    const reader = request.body.getReader();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        total += value.byteLength;
        if (total > MAX_BODY_BYTES) {
          await reader.cancel().catch(() => undefined);
          return { ok: false, response: payloadTooLarge(request) };
        }
        chunks.push(value);
      }
    } catch {
      return { ok: true, body: null };
    }
  }

  try {
    const merged = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.byteLength;
    }
    const parsed: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(merged));
    return { ok: true, body: isPlainObject(parsed) ? parsed : null };
  } catch {
    return { ok: true, body: null };
  }
}

/** 400 validation_error（設計仕様書 4.5 の形。FastAPI へ送る前に形・範囲だけ検査する）。拒否ログを 1 行書く（S9） */
export function validationError(request: Request, fields: { name: string; reason: string }[]): Response {
  logRejection(request, { event: "validation_rejected", status: 400, code: "validation_error" });
  return Response.json({ code: "validation_error", fields }, { status: 400, headers: { "Cache-Control": "no-store" } });
}
