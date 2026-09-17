/**
 * Cookie 文字列を組む純粋関数（設計仕様書 7.3・DS-DEC-14、テスト ST-SEC-07 の土台）。
 * Route Handler から `Set-Cookie` ヘッダにそのまま渡す。
 */

import { CSRF_TOKEN_COOKIE } from "@/lib/csrf-validation";

export const CART_TOKEN_COOKIE = "cart_token";
export const CART_TOKEN_MAX_AGE_SEC = 60 * 60 * 24 * 90; // 90 日

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

/** `Cookie` リクエストヘッダから指定名の値を取り出す（無ければ null） */
export function readCookie(cookieHeader: string | null, name: string): string | null {
  if (!cookieHeader) return null;
  for (const part of cookieHeader.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return rest.join("=");
  }
  return null;
}
