import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FixedWindowCounter, classifyPath, createRateLimiter } from "@/lib/server/rate-limit";

// セキュリティ強化 S1: 回数制限（IP ごと・60 秒の固定窓。/api/* は 120 回、ページ等は 600 回）。
// proxy.ts は import 時に環境変数を読むため、env を整えてから vi.resetModules() ＋動的 import で読み直す。

const ORIGINAL_ENV = { ...process.env };

function resetEnv() {
  process.env = { ...ORIGINAL_ENV };
  delete process.env.BASIC_AUTH_USER;
  delete process.env.BASIC_AUTH_PASSWORD;
  delete process.env.RATE_LIMIT_API_PER_MIN;
  delete process.env.RATE_LIMIT_PAGE_PER_MIN;
  // IP ごとの判定を見るため、信頼プロキシ 1 段（X-Forwarded-For の末尾を使う）にする
  process.env.TRUSTED_PROXY_HOPS = "1";
}

beforeEach(() => {
  resetEnv();
  vi.resetModules();
  vi.useFakeTimers({ now: new Date("2026-10-19T00:00:00Z") });
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  process.env = { ...ORIGINAL_ENV };
});

function req(path: string, ip = "203.0.113.5") {
  return new NextRequest(`http://localhost:3000${path}`, { headers: { "x-forwarded-for": ip } });
}

describe("S1 classifyPath（何を数えるか）", () => {
  it.each([
    ["/api/products", "api"],
    ["/api/cart/items/7", "api"],
    ["/api", "api"],
    ["/", "page"],
    ["/products/031", "page"],
    ["/cart", "page"],
    ["/products/031/1.jpg", "static"],
    ["/images/logo.svg", "static"],
    ["/_next/static/chunks/app.js", "static"],
    ["/_next/image", "static"],
    ["/favicon.ico", "static"],
  ])("%s は %s", (path, kind) => {
    expect(classifyPath(path)).toBe(kind);
  });

  it("/api/ 配下は拡張子が付いていても api として数える（静的ファイル扱いにしない）", () => {
    expect(classifyPath("/api/products.json")).toBe("api");
  });
});

describe("S1 FixedWindowCounter（メモリが増え続けない）", () => {
  it("窓が切れたキーは次の窓で捨てられる", () => {
    let now = 0;
    const counter = new FixedWindowCounter(60_000, () => now);
    for (let i = 0; i < 100; i++) counter.hit(`ip-${i}`, 10);
    expect(counter.size).toBe(100);
    now = 60_001;
    counter.hit("ip-new", 10);
    expect(counter.size).toBe(1);
  });

  it("キー数が上限に達したら古いキーから捨てる", () => {
    const counter = new FixedWindowCounter(60_000, () => 0, 3);
    for (const k of ["a", "b", "c", "d"]) counter.hit(k, 10);
    expect(counter.size).toBe(3);
  });

  it("createRateLimiter: 静的ファイルは null（数えない）", () => {
    const limiter = createRateLimiter({ apiPerMin: 1, pagePerMin: 1 });
    expect(limiter.check("/products/031/1.jpg", "1.2.3.4")).toBeNull();
    expect(limiter.check("/api/x", "1.2.3.4")?.allowed).toBe(true);
    expect(limiter.check("/api/x", "1.2.3.4")?.allowed).toBe(false);
  });
});

describe("S1 proxy の回数制限", () => {
  it("/api/* は 120 回まで通り、121 回目が 429・本文 rate_limited・Retry-After 付き", async () => {
    const { proxy } = await import("@/proxy");
    for (let i = 1; i <= 120; i++) {
      expect(proxy(req("/api/products")).status, `${i} 回目`).not.toBe(429);
    }
    vi.advanceTimersByTime(10_000); // 窓の開始から 10 秒後
    const res = proxy(req("/api/products"));
    expect(res.status).toBe(429);
    expect(await res.json()).toEqual({ code: "rate_limited" });
    expect(res.headers.get("Retry-After")).toBe("50");
    expect(res.headers.get("Cache-Control")).toBe("no-store");
  });

  it("ページ（RSC・prefetch 含む）は 600 回まで通り、601 回目が 429", async () => {
    const { proxy } = await import("@/proxy");
    for (let i = 1; i <= 600; i++) {
      const r = proxy(new NextRequest("http://localhost:3000/products/031?_rsc=abc", { headers: { "x-forwarded-for": "203.0.113.5", rsc: "1" } }));
      expect(r.status, `${i} 回目`).not.toBe(429);
    }
    expect(proxy(req("/cart")).status).toBe(429);
  });

  it("api とページは別々に数える（ページを使い切っても api は通る）", async () => {
    const { proxy } = await import("@/proxy");
    for (let i = 0; i < 601; i++) proxy(req("/"));
    expect(proxy(req("/")).status).toBe(429);
    expect(proxy(req("/api/products")).status).not.toBe(429);
  });

  it("静的ファイル（拡張子付き）は何回送っても数えず、429 にもならない", async () => {
    const { proxy } = await import("@/proxy");
    for (let i = 0; i < 700; i++) {
      expect(proxy(req("/products/031/1.jpg")).status).not.toBe(429);
    }
    // 静的ファイルで枠を使っていないので、ページ・api はまだ通る
    expect(proxy(req("/")).status).not.toBe(429);
    expect(proxy(req("/api/products")).status).not.toBe(429);
  });

  it("窓（60 秒）が切れたら通常に戻る", async () => {
    const { proxy } = await import("@/proxy");
    for (let i = 0; i < 121; i++) proxy(req("/api/products"));
    expect(proxy(req("/api/products")).status).toBe(429);
    vi.advanceTimersByTime(60_001);
    expect(proxy(req("/api/products")).status).not.toBe(429);
  });

  it("IP ごとに数える（別の IP は影響を受けない）", async () => {
    const { proxy } = await import("@/proxy");
    for (let i = 0; i < 121; i++) proxy(req("/api/products", "203.0.113.5"));
    expect(proxy(req("/api/products", "203.0.113.5")).status).toBe(429);
    expect(proxy(req("/api/products", "198.51.100.7")).status).not.toBe(429);
  });

  it("RATE_LIMIT_API_PER_MIN・RATE_LIMIT_PAGE_PER_MIN で上限を上書きできる", async () => {
    process.env.RATE_LIMIT_API_PER_MIN = "3";
    process.env.RATE_LIMIT_PAGE_PER_MIN = "5";
    const { proxy } = await import("@/proxy");
    for (let i = 0; i < 3; i++) expect(proxy(req("/api/x")).status).not.toBe(429);
    expect(proxy(req("/api/x")).status).toBe(429);
    for (let i = 0; i < 5; i++) expect(proxy(req("/cart")).status).not.toBe(429);
    expect(proxy(req("/cart")).status).toBe(429);
  });

  it("上限の環境変数が 0・小数・文字列なら import 時（起動時相当）に失敗する", async () => {
    for (const bad of ["0", "1.5", "abc", "-1"]) {
      process.env.RATE_LIMIT_API_PER_MIN = bad;
      vi.resetModules();
      await expect(import("@/proxy"), bad).rejects.toMatchObject({ name: "EnvValidationError" });
    }
  });

  it("429 のときは FastAPI を呼ばない（fetch を使わない）", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    process.env.RATE_LIMIT_API_PER_MIN = "1";
    const { proxy } = await import("@/proxy");
    proxy(req("/api/x"));
    expect(proxy(req("/api/x")).status).toBe(429);
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("Basic 認証が有効でも、上限を超えたら 401 ではなく 429 を返す（総当たりも数える）", async () => {
    process.env.BASIC_AUTH_USER = "reviewer";
    process.env.BASIC_AUTH_PASSWORD = "s3cret-demo"; // pragma: allowlist secret // gitleaks:allow
    process.env.RATE_LIMIT_PAGE_PER_MIN = "2";
    const { proxy } = await import("@/proxy");
    expect(proxy(req("/")).status).toBe(401);
    expect(proxy(req("/")).status).toBe(401);
    expect(proxy(req("/")).status).toBe(429);
  });
});
