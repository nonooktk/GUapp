import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { classifyPath, createRateLimiter } from "@/lib/server/rate-limit";
import { isAdminPath } from "@/lib/admin-types";

// テスト設計書 UT-WEB-53（proxy.ts と classifyPath。DS-DEC-122・126）・ST-SEC-95 の自動化部分
// proxy.ts は import 時に環境変数を読むため、env を整えてから vi.resetModules() ＋動的 import で読み直す。

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

function req(path: string, headers: Record<string, string> = {}, ip = "203.0.113.5") {
  return new NextRequest(`http://localhost:3000${path}`, { headers: { "x-forwarded-for": ip, ...headers } });
}

/** NextResponse.next({request:{headers}}) が下流へ渡すリクエストヘッダー（ブラウザには出ない内部ヘッダーに載る） */
function forwarded(res: Response): { overridden: string[]; get: (name: string) => string | null } {
  const list = res.headers.get("x-middleware-override-headers") ?? "";
  return {
    overridden: list.split(",").filter(Boolean),
    get: (name) => res.headers.get(`x-middleware-request-${name}`),
  };
}

describe("UT-WEB-53 proxy が付ける x-admin-area", () => {
  it.each([["/admin"], ["/admin/login"], ["/admin/products"], ["/admin/products/12"], ["/admin/api/csrf"], ["/admin/api/auth/login"]])(
    "%s には x-admin-area: 1 を付けて下流へ渡す",
    async (path) => {
      const { proxy } = await import("@/proxy");
      const res = proxy(req(path));
      expect(res.status).toBe(200);
      const f = forwarded(res);
      expect(f.get("x-admin-area")).toBe("1");
      expect(f.overridden).toContain("x-admin-area");
    },
  );

  it.each([["/"], ["/mypage"], ["/login"], ["/api/cart"], ["/products/12"], ["/administrator"], ["/adminx/products"]])(
    "%s には付けない。利用者が x-admin-area: 1 を付けても取り除く",
    async (path) => {
      const { proxy } = await import("@/proxy");
      const spoofed = forwarded(proxy(req(path, { "x-admin-area": "1" })));
      expect(spoofed.overridden).not.toContain("x-admin-area");
      expect(spoofed.get("x-admin-area")).toBeNull();
      const plain = forwarded(proxy(req(path)));
      expect(plain.overridden).not.toContain("x-admin-area");
    },
  );

  it("ほかのリクエストヘッダー(cookie・x-forwarded-for)は変えずに渡す。レスポンスヘッダーには x-admin-area を出さない", async () => {
    const { proxy } = await import("@/proxy");
    const res = proxy(req("/admin/products", { cookie: "asid=abc" }));
    const f = forwarded(res);
    expect(f.get("cookie")).toBe("asid=abc");
    expect(f.get("x-forwarded-for")).toBe("203.0.113.5");
    expect(res.headers.get("x-admin-area")).toBeNull();
  });

  it("Basic 認証が有効でも、通った /admin のリクエストに付く。通らなければ 401 で何も渡さない", async () => {
    process.env.BASIC_AUTH_USER = "reviewer";
    process.env.BASIC_AUTH_PASSWORD = "s3cret-demo"; // pragma: allowlist secret // gitleaks:allow
    const { proxy } = await import("@/proxy");
    const auth = `Basic ${Buffer.from("reviewer:s3cret-demo", "utf-8").toString("base64")}`; // pragma: allowlist secret // gitleaks:allow
    expect(forwarded(proxy(req("/admin/login", { authorization: auth }))).get("x-admin-area")).toBe("1");
    expect(forwarded(proxy(req("/mypage", { authorization: auth, "x-admin-area": "1" }))).get("x-admin-area")).toBeNull();
    const denied = proxy(req("/admin/login"));
    expect(denied.status).toBe(401);
    expect(denied.headers.get("x-middleware-override-headers")).toBeNull();
  });

  it("isAdminPath: /admin と /admin/ 配下だけ", () => {
    expect(isAdminPath("/admin")).toBe(true);
    expect(isAdminPath("/admin/")).toBe(true);
    expect(isAdminPath("/admin/x")).toBe(true);
    expect(isAdminPath("/administrator")).toBe(false);
    expect(isAdminPath("/Admin/x")).toBe(false);
    expect(isAdminPath("/x/admin")).toBe(false);
  });
});

describe("UT-WEB-53 classifyPath（管理 BFF は /api/* と同じ枠）", () => {
  it.each([
    ["/admin/api/csrf", "api"],
    ["/admin/api/auth/login", "api"],
    ["/admin/api/products/12", "api"],
    ["/admin/api/anything.json", "api"],
    ["/admin/api", "api"],
    ["/admin/login", "page"],
    ["/admin/products", "page"],
    ["/admin", "page"],
    ["/admin/apix", "page"],
    ["/api/cart", "api"],
    ["/mypage", "page"],
  ])("%s は %s", (path, kind) => {
    expect(classifyPath(path)).toBe(kind);
  });

  it("管理 BFF と /api/* は同じカウンタで数える（合わせて上限まで）。ページは別の枠", () => {
    const limiter = createRateLimiter({ apiPerMin: 3, pagePerMin: 100 });
    expect(limiter.check("/api/cart", "1.1.1.1")?.allowed).toBe(true);
    expect(limiter.check("/admin/api/csrf", "1.1.1.1")?.allowed).toBe(true);
    expect(limiter.check("/admin/api/csrf", "1.1.1.1")?.allowed).toBe(true);
    expect(limiter.check("/api/cart", "1.1.1.1")?.allowed).toBe(false);
    expect(limiter.check("/admin/products", "1.1.1.1")?.allowed).toBe(true);
    expect(limiter.check("/admin/api/csrf", "2.2.2.2")?.allowed).toBe(true);
  });
});

describe("ST-SEC-95 GET /admin/api/csrf を 120 回、121 回送る", () => {
  it("120 回目まで通り、121 回目は 429 rate_limited(Retry-After つき)。FastAPI を呼ばない", async () => {
    const { proxy } = await import("@/proxy");
    for (let i = 1; i <= 120; i++) {
      expect(proxy(req("/admin/api/csrf", {}, "198.51.100.7")).status).toBe(200);
    }
    const res = proxy(req("/admin/api/csrf", {}, "198.51.100.7"));
    expect(res.status).toBe(429);
    expect(await res.json()).toEqual({ code: "rate_limited" });
    expect(Number(res.headers.get("Retry-After"))).toBeGreaterThanOrEqual(1);
    // 別の IP は影響を受けない
    expect(proxy(req("/admin/api/csrf", {}, "198.51.100.8")).status).toBe(200);
  });
});
