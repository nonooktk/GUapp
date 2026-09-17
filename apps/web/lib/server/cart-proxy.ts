import "server-only";

import { buildCartTokenCookie, CART_TOKEN_COOKIE, readCookie } from "@/lib/cookie";
import { apiFetch, UpstreamUnavailableError } from "@/lib/server/api";
import { issueCsrfCookieIfMissing } from "@/lib/server/csrf";
import { getEnv } from "@/lib/server/env";
import type { Cart } from "@/lib/types";

/**
 * カート BFF の共通取り次ぎ（DS-API-010〜013・設計仕様書 4.3・7.3）。
 * - Cookie `cart_token` を `X-Cart-Token` ヘッダに載せて FastAPI を呼ぶ（トークン発行者は FastAPI）
 * - 応答の `cart_token` が Cookie と異なる（または Cookie 無し）なら `Set-Cookie: cart_token=…`
 * - Cookie `csrf_token` が未発行なら同時に発行する
 * - FastAPI のエラーは sanitizeErrorBody 済みの `{code, ...}` をそのままの status で返す
 * - 接続不可は 503 `{code:"upstream_unavailable"}`
 */

export const CART_TOKEN_HEADER = "X-Cart-Token";

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
    result = await apiFetch<Cart>(path, {
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

  const cart = result.data;
  const env = getEnv();
  if (typeof cart?.cart_token === "string" && cart.cart_token !== currentToken) {
    headers.append("Set-Cookie", buildCartTokenCookie(cart.cart_token, env.APP_ENV, env.SESSION_COOKIE_DOMAIN));
  }
  const csrfCookie = issueCsrfCookieIfMissing(request);
  if (csrfCookie) headers.append("Set-Cookie", csrfCookie);

  return Response.json(cart, { status: result.status, headers });
}

/** JSON 本文を読む。壊れていれば null（呼び出し側で 400 validation_error にする） */
export async function readJsonBody(request: Request): Promise<Record<string, unknown> | null> {
  try {
    const body: unknown = await request.json();
    return typeof body === "object" && body !== null ? (body as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** 400 validation_error（設計仕様書 4.5 の形。FastAPI へ送る前に形だけ検査する） */
export function validationError(fields: { name: string; reason: string }[]): Response {
  return Response.json({ code: "validation_error", fields }, { status: 400, headers: { "Cache-Control": "no-store" } });
}
