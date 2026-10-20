/**
 * P2-b の BFF テスト共通部品。import した時点で環境変数を用意する（getEnv() は初回に process.env を読んでキャッシュするため、
 * Route Handler を import する前に評価されるよう、テストファイルの先頭で import すること）。
 */
process.env.API_BASE_URL = "http://fastapi.test:8000";
process.env.INTERNAL_TOKEN = "dummy-internal-token"; // gitleaks:allow // pragma: allowlist secret（テスト用ダミー）
process.env.IMAGE_BASE_URL = "http://localhost:3000";
process.env.APP_ENV = "development";
process.env.SESSION_COOKIE_DOMAIN = "";

export const CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret
export const SID_OLD = "oldSidAAAA_-0123456789abcdefghijklmnopqrstu"; // gitleaks:allow // pragma: allowlist secret（43 文字）
export const SID_NEW = "newSidBBBB_-0123456789abcdefghijklmnopqrstu"; // gitleaks:allow // pragma: allowlist secret（43 文字）
export const CART_TOKEN = "cartTokenAAAA_-0123456789abcdefghijklmnopq"; // gitleaks:allow // pragma: allowlist secret

/** FastAPI の応答（fetch モックの戻り値） */
export function upstream(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  if (status === 204) return new Response(null, { status, headers });
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

/** CSRF 付きの正規のリクエストヘッダ（Cookie の csrf_token とヘッダを一致させる）。cookies は追加の Cookie（`sid=…` など） */
export function csrfHeaders(extraCookies = "", extra: Record<string, string> = {}): Record<string, string> {
  return {
    cookie: [`csrf_token=${CSRF}`, extraCookies].filter(Boolean).join("; "),
    "X-CSRF-Token": CSRF,
    "Content-Type": "application/json",
    ...extra,
  };
}

export function jsonPost(path: string, body: unknown, headers: Record<string, string>): Request {
  return new Request(`http://localhost:3000${path}`, {
    method: "POST",
    body: typeof body === "string" ? body : JSON.stringify(body),
    headers,
  });
}

/** Set-Cookie ヘッダを名前で探す（`name=value; 属性…` の文字列全体を返す） */
export function findSetCookie(res: Response, name: string): string | undefined {
  return res.headers.getSetCookie().find((c) => c.startsWith(`${name}=`));
}

/** fetch モックの n 回目の呼び出しの [url, init, Headers] */
export function callOf(mock: { mock: { calls: unknown[][] } }, n = 0): { url: string; init: RequestInit; headers: Headers; body: unknown } {
  const [url, init] = mock.mock.calls[n] as [string, RequestInit];
  return {
    url,
    init,
    headers: new Headers(init.headers),
    body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
  };
}
