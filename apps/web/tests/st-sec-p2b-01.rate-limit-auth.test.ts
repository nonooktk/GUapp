import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { classifyPath } from "@/lib/server/rate-limit";

// ST-SEC-58（BFF の全体制限 S1 が新しい窓口にも掛かること）の自動化できる部分。設計仕様書 4.0・7.1（B-04）
// 個別の回数制限（登録 10 回/時 など）は FastAPI 側（IT／ST で確認）。ここは BFF の proxy.ts が新しい 7 本の窓口を `/api/*` として数えることだけを確かめる。
const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env = { ...ORIGINAL_ENV };
  delete process.env.BASIC_AUTH_USER;
  delete process.env.BASIC_AUTH_PASSWORD;
  delete process.env.RATE_LIMIT_API_PER_MIN;
  delete process.env.RATE_LIMIT_PAGE_PER_MIN;
  process.env.TRUSTED_PROXY_HOPS = "1";
  vi.resetModules();
  vi.useFakeTimers({ now: new Date("2026-10-20T00:00:00Z") });
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  process.env = { ...ORIGINAL_ENV };
});

const NEW_ROUTES = [
  "/api/auth/register",
  "/api/auth/verify-email",
  "/api/auth/login",
  "/api/auth/logout",
  "/api/auth/password-reset/request",
  "/api/auth/password-reset/confirm",
  "/api/restock-notifications",
];

describe("ST-SEC-58（BFF 側）新しい窓口は /api/* として数える", () => {
  it.each(NEW_ROUTES)("%s は api", (path) => {
    expect(classifyPath(path)).toBe("api");
  });

  it("同じ IP が /api/auth/login を 121 回送ると 121 回目が 429 rate_limited（Retry-After つき）。別の IP は通る", async () => {
    const { proxy } = await import("@/proxy");
    const req = (ip: string) => new NextRequest("http://localhost:3000/api/auth/login", { method: "POST", headers: { "x-forwarded-for": ip } });
    for (let i = 0; i < 120; i++) expect(proxy(req("203.0.113.5")).status).toBe(200);
    const limited = proxy(req("203.0.113.5"));
    expect(limited.status).toBe(429);
    expect(limited.headers.get("Retry-After")).toMatch(/^\d+$/);
    expect(await limited.json()).toEqual({ code: "rate_limited" });
    expect(proxy(req("203.0.113.6")).status).toBe(200);
  });
});
