/**
 * Cookie 文字列を組む純粋関数（設計仕様書 7.3・DS-DEC-14、テスト ST-SEC-07 の土台）。
 * Route Handler から `Set-Cookie` ヘッダにそのまま渡す。
 */

import { CSRF_TOKEN_COOKIE } from "@/lib/csrf-validation";

export const CART_TOKEN_COOKIE = "cart_token";
export const CART_TOKEN_MAX_AGE_SEC = 60 * 60 * 24 * 90; // 90 日

/** 会員セッション Cookie（設計仕様書 7.3・DS-DEC-72）。値は FastAPI が発行した 43 文字の base64url。BFF は中身を解釈しない */
export const SESSION_COOKIE = "sid";
export const SESSION_MAX_AGE_SEC = 60 * 60 * 24; // 24 時間（作成から固定。延長しない）
/** `sid`・`X-Session-Token` の値の形（32 バイト乱数の base64url 43 文字） */
export const SESSION_TOKEN_SHAPE = /^[A-Za-z0-9_-]{43}$/;

/** BFF → FastAPI の会員セッション用ヘッダ名（`X-Cart-Token` と同じ方式。設計仕様書 4.0） */
export const SESSION_TOKEN_HEADER = "X-Session-Token";

export interface CookieOptions {
  /** `production` のときだけ Secure を付ける（ローカル http では保存されないため。設計 7.3） */
  appEnv: string;
  /** Domain 属性。空なら付けない（ローカル） */
  domain?: string;
  maxAgeSec: number;
  path?: string;
  sameSite?: "Lax" | "Strict";
  /** 既定 true。CSRF トークン Cookie だけはクライアント JS が読む必要があるため false にする */
  httpOnly?: boolean;
}

/** 値は英数・`-`・`_`・`.` のみ許可（base64url など）。改行等によるヘッダ注入を防ぐ */
const SAFE_VALUE = /^[A-Za-z0-9._-]*$/;

export function buildSetCookie(name: string, value: string, options: CookieOptions): string {
  if (!SAFE_VALUE.test(value)) {
    throw new Error("Cookie の値に使えない文字が含まれています");
  }
  const parts = [`${name}=${value}`];
  parts.push(`Path=${options.path ?? "/"}`);
  parts.push(`Max-Age=${options.maxAgeSec}`);
  if (options.httpOnly ?? true) parts.push("HttpOnly");
  parts.push(`SameSite=${options.sameSite ?? "Lax"}`);
  if (options.domain) parts.push(`Domain=${options.domain}`);
  if (options.appEnv === "production") parts.push("Secure");
  return parts.join("; ");
}

/** 匿名カートトークン Cookie（HttpOnly・SameSite=Lax・90 日） */
export function buildCartTokenCookie(token: string, appEnv: string, domain = ""): string {
  return buildSetCookie(CART_TOKEN_COOKIE, token, {
    appEnv,
    domain,
    maxAgeSec: CART_TOKEN_MAX_AGE_SEC,
  });
}

/**
 * CSRF トークン Cookie（Double Submit Cookie。設計仕様書 7.3）。
 * クライアント JS が `document.cookie` から読んで `X-CSRF-Token` ヘッダに載せるため HttpOnly を付けない。
 * SameSite=Lax・Secure は production のみ。寿命はカートトークンと同じ 90 日。
 */
export function buildCsrfTokenCookie(token: string, appEnv: string, domain = ""): string {
  return buildSetCookie(CSRF_TOKEN_COOKIE, token, {
    appEnv,
    domain,
    maxAgeSec: CART_TOKEN_MAX_AGE_SEC,
    httpOnly: false,
  });
}

/**
 * 会員セッション Cookie `sid`（HttpOnly・SameSite=Lax・Path=/・Max-Age=86400。Secure は production のみ）。
 * 値に使えない文字（改行・`;` など）を含むと例外（ヘッダ注入を防ぐ）。
 */
export function buildSessionCookie(token: string, appEnv: string, domain = ""): string {
  return buildSetCookie(SESSION_COOKIE, token, { appEnv, domain, maxAgeSec: SESSION_MAX_AGE_SEC });
}

/** `sid` の削除用 Cookie（値は空・Max-Age=0）。ログアウトの応答で必ず返す */
export function buildSessionDeleteCookie(appEnv: string, domain = ""): string {
  return buildSetCookie(SESSION_COOKIE, "", { appEnv, domain, maxAgeSec: 0 });
}

/** `Cookie` リクエストヘッダから指定名の値を取り出す（無ければ null） */
export function readCookie(cookieHeader: string | null, name: string): string | null {
  if (!cookieHeader) return null;
  for (const part of cookieHeader.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return rest.join("=");
  }
  return null;
}

/**
 * リクエストの Cookie から `sid` を取り出す。形（43 文字の base64url）が違う値は「セッションなし」として null を返す
 * （ヘッダにそのまま載せて注入や 500 になるのを避ける。値の意味は解釈しない）。
 */
export function readSessionToken(cookieHeader: string | null): string | null {
  const v = readCookie(cookieHeader, SESSION_COOKIE);
  return v !== null && SESSION_TOKEN_SHAPE.test(v) ? v : null;
}

// ---- P2-d: AI アシスタントの会話トークン Cookie（設計仕様書 P2 追補d 4.4・DS-DEC-97） ----

export const CHAT_TOKEN_COOKIE = "chat_token";
export const CHAT_TOKEN_MAX_AGE_SEC = 60 * 60; // 1 時間

/** FastAPI が発行する会話トークンの形（`secrets.token_urlsafe(32)` ＝ base64url 43 文字） */
const CHAT_TOKEN_SHAPE = /^[A-Za-z0-9_-]{43}$/;

export function isChatTokenShape(value: string | null | undefined): value is string {
  return typeof value === "string" && CHAT_TOKEN_SHAPE.test(value);
}

/** 会話トークン Cookie（HttpOnly・SameSite=Lax・Path=/・1 時間。Domain は付けない＝この host だけ） */
export function buildChatTokenCookie(token: string, appEnv: string): string {
  return buildSetCookie(CHAT_TOKEN_COOKIE, token, { appEnv, maxAgeSec: CHAT_TOKEN_MAX_AGE_SEC });
}

/** 会話トークン Cookie を消す（`Max-Age=0`。「新しい相談」で使う） */
export function buildChatTokenClearCookie(appEnv: string): string {
  return buildSetCookie(CHAT_TOKEN_COOKIE, "", { appEnv, maxAgeSec: 0 });
}
