import { buildSetCookie, readCookie, SESSION_TOKEN_SHAPE } from "@/lib/cookie";

/**
 * 管理用セッション Cookie `asid` の組み立て（設計仕様書 P2 追補c 7.3・DS-DEC-108、テスト UT-WEB-40・ST-SEC-83）。
 * 純粋関数なので `server-only` を付けず、Vitest から直接テストできる。会員の `sid`（lib/cookie.ts）とは別の Cookie・別のヘッダで、混ぜない。
 *
 * - `HttpOnly`・`SameSite=Strict`・`Path=/admin`・`Max-Age=28800`（8 時間の固定。延長しない）。`Secure` は production のみ（buildSetCookie の既存の方針）
 * - 値は FastAPI が発行した 43 文字の base64url。BFF は中身を解釈せず、形の検査だけを行う
 * - `Path=/admin` なので、公開サイトのリクエスト（`/`・`/mypage`・`/api/*`）には付かない
 */

export const ADMIN_SESSION_COOKIE = "asid";
export const ADMIN_SESSION_MAX_AGE_SEC = 60 * 60 * 8;
export const ADMIN_COOKIE_PATH = "/admin";
/** BFF／Server Component → FastAPI の管理用セッションヘッダ名（会員の `X-Session-Token` とは別） */
export const ADMIN_SESSION_TOKEN_HEADER = "X-Admin-Session-Token";

export function buildAdminSessionCookie(token: string, appEnv: string, domain = ""): string {
  return buildSetCookie(ADMIN_SESSION_COOKIE, token, {
    appEnv,
    domain,
    maxAgeSec: ADMIN_SESSION_MAX_AGE_SEC,
    path: ADMIN_COOKIE_PATH,
    sameSite: "Strict",
  });
}

/** `asid` の削除用 Cookie（値は空・Max-Age=0・`Path=/admin`）。ログアウトの応答で必ず返す */
export function buildAdminSessionDeleteCookie(appEnv: string, domain = ""): string {
  return buildSetCookie(ADMIN_SESSION_COOKIE, "", {
    appEnv,
    domain,
    maxAgeSec: 0,
    path: ADMIN_COOKIE_PATH,
    sameSite: "Strict",
  });
}

/** `asid` の値として妥当な形か（43 文字の base64url） */
export function isAdminSessionTokenShape(value: string | null | undefined): value is string {
  return typeof value === "string" && SESSION_TOKEN_SHAPE.test(value);
}

/**
 * リクエストの Cookie から `asid` を取り出す。形が違う値は「セッションなし」として null を返す
 * （ヘッダにそのまま載せて注入や 500 になるのを避ける。値の意味は解釈しない）。
 */
export function readAdminSessionToken(cookieHeader: string | null): string | null {
  const v = readCookie(cookieHeader, ADMIN_SESSION_COOKIE);
  return isAdminSessionTokenShape(v) ? v : null;
}
