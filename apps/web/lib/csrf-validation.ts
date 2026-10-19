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

/**
 * Origin の確認（セキュリティ強化 S6）。トークン照合の前の段として使う純粋関数。
 * - `Origin` があれば、そのホスト（host:port）が自サイトのホストと一致するときだけ通す（"null" や壊れた値は拒否）
 * - `Origin` が無く `Sec-Fetch-Site` があれば、`same-origin` のときだけ通す
 * - どちらも無い（curl など）ときは通す（従来どおりトークン照合だけに任せる）
 *
 * 自サイトのホストは `X-Forwarded-Host` の先頭（App Service の背後でも利用者向けのホストが取れる）→ `Host` → リクエスト URL の順。
 */
export interface OriginCheckInput {
  origin: string | null;
  secFetchSite: string | null;
  xForwardedHost: string | null;
  host: string | null;
  /** `Host` も無いときの最後の手段（Request.url のホスト） */
  urlHost?: string | null;
}

export function ownHost(input: Pick<OriginCheckInput, "xForwardedHost" | "host" | "urlHost">): string | null {
  const forwarded = input.xForwardedHost?.split(",")[0]?.trim().toLowerCase();
  if (forwarded) return forwarded;
  const host = input.host?.trim().toLowerCase();
  if (host) return host;
  return input.urlHost?.trim().toLowerCase() || null;
}

export function isOriginAllowed(input: OriginCheckInput): boolean {
  if (input.origin !== null && input.origin !== "") {
    let originHost: string;
    try {
      originHost = new URL(input.origin).host.toLowerCase();
    } catch {
      return false;
    }
    if (originHost === "") return false;
    const own = ownHost(input);
    return own !== null && own === originHost;
  }
  if (input.secFetchSite !== null && input.secFetchSite !== "") {
    return input.secFetchSite.trim().toLowerCase() === "same-origin";
  }
  return true;
}
