import { buildCartTokenCookie, CART_TOKEN_COOKIE, readCookie } from "@/lib/cookie";
import { generateCartToken } from "@/lib/server/cart-token";
import { getEnv } from "@/lib/server/env";

/**
 * カート BFF（DS-API-010 取り次ぎ先）。Wave 0 は Cookie 発行方式の先行確認のみ（プラン 7 章のリスク対策）。
 * GET: Cookie `cart_token` が無ければ暗号学的乱数 32 バイト（base64url）で発行する。
 *   属性: HttpOnly・SameSite=Lax・Path=/・Max-Age 90 日・Secure は APP_ENV=production のみ（設計 7.3）。
 *   本文は仮応答 `{cart_token_issued: true|false}`。FastAPI 連携は Wave 1。
 */

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const env = getEnv();
  const existing = readCookie(request.headers.get("cookie"), CART_TOKEN_COOKIE);

  if (existing) {
    return Response.json({ cart_token_issued: false }, { status: 200 });
  }

  const token = generateCartToken();
  return Response.json(
    { cart_token_issued: true },
    {
      status: 200,
      headers: {
        "Set-Cookie": buildCartTokenCookie(token, env.APP_ENV, env.SESSION_COOKIE_DOMAIN),
        "Cache-Control": "no-store",
      },
    },
  );
}
