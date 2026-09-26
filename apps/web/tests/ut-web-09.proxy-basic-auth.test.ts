import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// テスト設計書 UT-WEB-09 / ST-SEC-16〜18: Next.js 16 の proxy（旧 middleware）による
// サイト全体・BFF `/api/*` への Basic 認証（公開追補 設計仕様書 7 章・DS-DEC-49）。
//
// `proxy.ts` はモジュール読み込み時（import 時）に環境変数を一度だけ読む設計のため、
// 各テストで env を設定してから `vi.resetModules()` ＋ 動的 import で読み直す。

const ORIGINAL_ENV = { ...process.env };

function resetEnv() {
  process.env = { ...ORIGINAL_ENV };
  delete process.env.BASIC_AUTH_USER;
  delete process.env.BASIC_AUTH_PASSWORD;
}

beforeEach(() => {
  resetEnv();
  vi.resetModules();
});

afterEach(() => {
  resetEnv();
});

function basicHeader(user: string, password: string): string {
  return `Basic ${Buffer.from(`${user}:${password}`, "utf-8").toString("base64")}`;
}

describe("UT-WEB-09 proxy（Basic 認証）", () => {
  it("BASIC_AUTH_USER・PASSWORD が両方未設定なら 401 にしない（ローカル開発を妨げない）", async () => {
    const { proxy } = await import("@/proxy");
    const res = proxy(new NextRequest("http://localhost:3000/"));
    expect(res.status).not.toBe(401);
    expect(res.headers.get("WWW-Authenticate")).toBeNull();
  });

  it("片方だけ設定されていると import 時（起動時相当）に BasicAuthConfigError で失敗する", async () => {
    process.env.BASIC_AUTH_USER = "reviewer";
    // vi.resetModules() 後の動的 import なので、静的 import した BasicAuthConfigError とは
    // 別のモジュールインスタンスになりうる（instanceof ではなく name で判定する）
    await expect(import("@/proxy")).rejects.toMatchObject({ name: "BasicAuthConfigError" });
  });

  it("両方設定・Authorization ヘッダ無しは 401 と WWW-Authenticate", async () => {
    process.env.BASIC_AUTH_USER = "reviewer";
    process.env.BASIC_AUTH_PASSWORD = "s3cret-demo"; // pragma: allowlist secret // gitleaks:allow
    const { proxy } = await import("@/proxy");
    const res = proxy(new NextRequest("http://localhost:3000/"));
    expect(res.status).toBe(401);
    expect(res.headers.get("WWW-Authenticate")).toBe('Basic realm="GUapp demo", charset="UTF-8"');
  });

  it("両方設定・誤った認証情報は 401", async () => {
    process.env.BASIC_AUTH_USER = "reviewer";
    process.env.BASIC_AUTH_PASSWORD = "s3cret-demo"; // pragma: allowlist secret // gitleaks:allow
    const { proxy } = await import("@/proxy");
    const req = new NextRequest("http://localhost:3000/api/products", {
      headers: { authorization: basicHeader("reviewer", "wrong-password") },
    });
    const res = proxy(req);
    expect(res.status).toBe(401);
  });

  it("両方設定・正しい認証情報は 401 にしない（/api/ 配下も対象）", async () => {
    process.env.BASIC_AUTH_USER = "reviewer";
    process.env.BASIC_AUTH_PASSWORD = "s3cret-demo"; // pragma: allowlist secret // gitleaks:allow
    const { proxy } = await import("@/proxy");
    const req = new NextRequest("http://localhost:3000/api/cart", {
      headers: { authorization: basicHeader("reviewer", "s3cret-demo") },
    });
    const res = proxy(req);
    expect(res.status).not.toBe(401);
  });

  it("config.matcher は _next/static・_next/image・favicon 等を除外し、それ以外（/api/* 含む）を対象にする", async () => {
    const { config } = await import("@/proxy");
    expect(Array.isArray(config.matcher) ? config.matcher : [config.matcher]).toEqual([
      "/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)",
    ]);
  });
});
