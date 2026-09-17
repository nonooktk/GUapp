/**
 * CSRF（Double Submit Cookie）の判定ルール。設計仕様書 7.3・4.5（403 forbidden）。
 * 純粋関数なので `server-only` を付けず Vitest から直接テストする。乱数生成・Request の読み取りは lib/server/csrf.ts。
 */

export const CSRF_TOKEN_COOKIE = "csrf_token";
export const CSRF_HEADER = "X-CSRF-Token";
/** 32 バイト乱数を base64url にした長さ（43 文字）。形の検証に使う */
export const CSRF_TOKEN_LENGTH = 43;

const TOKEN_SHAPE = /^[A-Za-z0-9_-]{43}$/;

/** 発行済みトークンとして妥当な形か */
export function isCsrfTokenShape(value: string | null | undefined): value is string {
  return typeof value === "string" && TOKEN_SHAPE.test(value);
}

/**
 * Cookie の値とヘッダの値が両方あり、形が正しく、一致するときだけ通す。
 * 比較は長さ固定の定数時間比較（タイミング差で 1 文字ずつ当てられないようにする）。
 */
export function isCsrfValid(cookieValue: string | null | undefined, headerValue: string | null | undefined): boolean {
  if (!isCsrfTokenShape(cookieValue) || !isCsrfTokenShape(headerValue)) return false;
  let diff = 0;
  for (let i = 0; i < CSRF_TOKEN_LENGTH; i++) {
    diff |= cookieValue.charCodeAt(i) ^ headerValue.charCodeAt(i);
  }
  return diff === 0;
}
