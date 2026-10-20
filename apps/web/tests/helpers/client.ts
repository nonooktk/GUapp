import { vi } from "vitest";

/** ブラウザ側の `csrf_token` Cookie を用意する（ensureCsrfToken が GET /api/cart を呼ばずに済む） */
export const CLIENT_CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret

export function setCsrfCookie(): void {
  document.cookie = `csrf_token=${CLIENT_CSRF}; path=/`;
}

export function clearCookies(): void {
  for (const part of document.cookie.split(";")) {
    const name = part.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; path=/; max-age=0`;
  }
}

export function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  if (status === 204) return new Response(null, { status });
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

/** fetch をモックし、呼び出し（url・method・本文・ヘッダ）を配列で見られるようにする */
export function mockFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const calls: { url: string; method: string; body: unknown; headers: Headers }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    calls.push({
      url,
      method: init.method ?? "GET",
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
      headers: new Headers(init.headers),
    });
    return handler(url, init);
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}
