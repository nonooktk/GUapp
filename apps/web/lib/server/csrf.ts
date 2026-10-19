import "server-only";

import { randomBytes } from "node:crypto";
import { buildCsrfTokenCookie, readCookie } from "@/lib/cookie";
import {
  CSRF_HEADER,
  CSRF_TOKEN_COOKIE,
  isCsrfTokenShape,
  isCsrfValid,
  isOriginAllowed,
} from "@/lib/csrf-validation";
import { getEnv } from "@/lib/server/env";
import { logRejection } from "@/lib/server/security-log";

/**
 * CSRF（Double Submit Cookie）の Route Handler 向けヘルパー（設計仕様書 7.3・4.5）。
 * 判定ルールは lib/csrf-validation.ts の純粋関数。ここでは乱数発行と Request/Response の受け渡しだけを担う。
 * Wave 2 の `/api/checkout/prepare`・`/api/orders` もこの 2 関数をそのまま使う。
 */

/** 暗号学的乱数 32 バイトの base64url（43 文字） */
export function generateCsrfToken(): string {
  return randomBytes(32).toString("base64url");
}

/**
 * 状態変更リクエストの CSRF を検証する。通れば null、拒否なら 403 `{code:"forbidden"}` の Response を返す。
 * 呼び出し側は `const denied = verifyCsrf(request); if (denied) return denied;` として FastAPI へ到達させない。
 *
 * 順序（S6）: ① Origin／Sec-Fetch-Site が自サイトのものか → ② Double Submit Cookie のトークン照合。
 * 拒否したときは 1 行の警告ログを書く（本文・Cookie・トークンは出さない。S9）。
 */
export function verifyCsrf(request: Request): Response | null {
  if (!isOriginAllowed(requestOriginInput(request))) {
    logRejection(request, { event: "origin_rejected", status: 403, code: "forbidden" });
    return forbidden();
  }
  const cookieValue = readCookie(request.headers.get("cookie"), CSRF_TOKEN_COOKIE);
  const headerValue = request.headers.get(CSRF_HEADER);
  if (isCsrfValid(cookieValue, headerValue)) return null;
  logRejection(request, { event: "csrf_token_rejected", status: 403, code: "forbidden" });
  return forbidden();
}

function forbidden(): Response {
  return Response.json({ code: "forbidden" }, { status: 403, headers: { "Cache-Control": "no-store" } });
}

function requestOriginInput(request: Request) {
  let urlHost: string | null = null;
  try {
    urlHost = new URL(request.url).host;
  } catch {
    urlHost = null;
  }
  return {
    origin: request.headers.get("origin"),
    secFetchSite: request.headers.get("sec-fetch-site"),
    xForwardedHost: request.headers.get("x-forwarded-host"),
    host: request.headers.get("host"),
    urlHost,
  };
}

/**
 * Cookie `csrf_token` が未発行（または形が不正）なら新規発行の Set-Cookie ヘッダ文字列を返す。発行済みなら null。
 * `GET /api/cart` の応答で使う（Server Component では Cookie を発行できないため Route Handler に集める）。
 */
export function issueCsrfCookieIfMissing(request: Request): string | null {
  const existing = readCookie(request.headers.get("cookie"), CSRF_TOKEN_COOKIE);
  if (isCsrfTokenShape(existing)) return null;
  const env = getEnv();
  return buildCsrfTokenCookie(generateCsrfToken(), env.APP_ENV, env.SESSION_COOKIE_DOMAIN);
}
