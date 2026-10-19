import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { isOriginAllowed, ownHost } from "@/lib/csrf-validation";

// セキュリティ強化 S6: CSRF に Origin の確認を足す（verifyCsrf のトークン照合の前の段）。
process.env.API_BASE_URL = "http://fastapi.test:8000";
process.env.INTERNAL_TOKEN = "dummy-internal-token"; // gitleaks:allow（テスト用ダミー）
process.env.IMAGE_BASE_URL = "http://localhost:3000";
process.env.APP_ENV = "development";
process.env.SESSION_COOKIE_DOMAIN = "";

const CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret
const base = { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF };

let verifyCsrf: typeof import("@/lib/server/csrf").verifyCsrf;
beforeAll(async () => {
  ({ verifyCsrf } = await import("@/lib/server/csrf"));
});

beforeEach(() => {
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.restoreAllMocks();
});

function post(headers: Record<string, string>, url = "http://localhost:3000/api/cart/items") {
  return new Request(url, { method: "POST", headers: { ...base, ...headers } });
}

describe("S6 verifyCsrf の Origin 確認", () => {
  it("別の Origin は 403 forbidden（トークンが正しくても）", async () => {
    const res = verifyCsrf(post({ host: "shop.example.com", origin: "https://evil.example.net" }));
    expect(res?.status).toBe(403);
    expect(await res?.json()).toEqual({ code: "forbidden" });
  });

  it("同じ Origin（Host と一致）なら通る", () => {
    expect(verifyCsrf(post({ host: "shop.example.com", origin: "https://shop.example.com" }))).toBeNull();
  });

  it("ポート違いは別オリジン（localhost:3000 と localhost:3001）", () => {
    expect(verifyCsrf(post({ host: "localhost:3000", origin: "http://localhost:3001" }))?.status).toBe(403);
    expect(verifyCsrf(post({ host: "localhost:3000", origin: "http://localhost:3000" }))).toBeNull();
  });

  it("X-Forwarded-Host があればそれを使う（App Service の背後。Host は内部名でも通る）", () => {
    const headers = { host: "internal-app:8080", "x-forwarded-host": "shop.example.com", origin: "https://shop.example.com" };
    expect(verifyCsrf(post(headers))).toBeNull();
    // Host と一致していても、X-Forwarded-Host と違えば拒否（X-Forwarded-Host が優先）
    expect(
      verifyCsrf(post({ host: "internal-app:8080", "x-forwarded-host": "shop.example.com", origin: "http://internal-app:8080" }))
        ?.status,
    ).toBe(403);
  });

  it("X-Forwarded-Host が複数なら先頭を使う", () => {
    expect(
      verifyCsrf(post({ "x-forwarded-host": "shop.example.com, proxy.internal", origin: "https://shop.example.com" })),
    ).toBeNull();
  });

  it("Origin: null や壊れた値は 403", () => {
    expect(verifyCsrf(post({ host: "localhost:3000", origin: "null" }))?.status).toBe(403);
    expect(verifyCsrf(post({ host: "localhost:3000", origin: "not a url" }))?.status).toBe(403);
  });

  it("Origin が無く Sec-Fetch-Site が cross-site なら 403", () => {
    expect(verifyCsrf(post({ "sec-fetch-site": "cross-site" }))?.status).toBe(403);
    expect(verifyCsrf(post({ "sec-fetch-site": "same-site" }))?.status).toBe(403);
    expect(verifyCsrf(post({ "sec-fetch-site": "none" }))?.status).toBe(403);
  });

  it("Origin が無く Sec-Fetch-Site が same-origin なら通る", () => {
    expect(verifyCsrf(post({ "sec-fetch-site": "same-origin" }))).toBeNull();
  });

  it("どちらも無い（curl など）ときは従来どおりトークン照合だけ", () => {
    expect(verifyCsrf(post({}))).toBeNull();
    // トークンが違えば従来どおり 403
    const bad = new Request("http://localhost:3000/api/cart/items", {
      method: "POST",
      headers: { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF.slice(0, -1) + "Z" },
    });
    expect(verifyCsrf(bad)?.status).toBe(403);
  });

  it("Origin が一致してもトークンが無ければ 403（Origin はトークン照合の代わりではない）", () => {
    const req = new Request("http://localhost:3000/api/cart/items", {
      method: "POST",
      headers: { host: "localhost:3000", origin: "http://localhost:3000" },
    });
    expect(verifyCsrf(req)?.status).toBe(403);
  });
});

describe("S6 isOriginAllowed / ownHost（純粋関数）", () => {
  it("Host も X-Forwarded-Host も無ければ URL のホストと比べる", () => {
    expect(
      isOriginAllowed({ origin: "http://localhost:3000", secFetchSite: null, xForwardedHost: null, host: null, urlHost: "localhost:3000" }),
    ).toBe(true);
    expect(
      isOriginAllowed({ origin: "http://evil.test", secFetchSite: null, xForwardedHost: null, host: null, urlHost: "localhost:3000" }),
    ).toBe(false);
  });

  it("自サイトのホストが分からないときは Origin があれば拒否", () => {
    expect(isOriginAllowed({ origin: "http://localhost:3000", secFetchSite: null, xForwardedHost: null, host: null })).toBe(false);
  });

  it("ownHost: X-Forwarded-Host の先頭 → Host → URL。大文字小文字は区別しない", () => {
    expect(ownHost({ xForwardedHost: "A.example.com, b", host: "c", urlHost: "d" })).toBe("a.example.com");
    expect(ownHost({ xForwardedHost: null, host: "C.example.com", urlHost: "d" })).toBe("c.example.com");
    expect(ownHost({ xForwardedHost: " ", host: null, urlHost: "d:1" })).toBe("d:1");
  });
});
