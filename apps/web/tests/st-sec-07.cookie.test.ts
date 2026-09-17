import { describe, expect, it } from "vitest";
import { buildCartTokenCookie, buildSetCookie, CART_TOKEN_MAX_AGE_SEC, readCookie } from "@/lib/cookie";

// テスト設計書 ST-SEC-07（匿名トークン Cookie の属性）の土台。設計仕様書 7.3・プラン 5 章「Cookie の Secure」
describe("ST-SEC-07 buildCartTokenCookie", () => {
  const token = "abcDEF123_-xyz"; // gitleaks:allow（Cookie 属性検証用のダミー値。秘密ではない）

  it("APP_ENV=development では HttpOnly・SameSite=Lax が付き、Secure が付かない", () => {
    const cookie = buildCartTokenCookie(token, "development");
    expect(cookie).toContain(`cart_token=${token}`);
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Lax");
    expect(cookie).toContain("Path=/");
    expect(cookie).toContain(`Max-Age=${CART_TOKEN_MAX_AGE_SEC}`);
    expect(cookie).not.toMatch(/\bSecure\b/);
  });

  it("APP_ENV=test でも Secure が付かない", () => {
    expect(buildCartTokenCookie(token, "test")).not.toMatch(/\bSecure\b/);
  });

  it("APP_ENV=production では Secure が付く", () => {
    const cookie = buildCartTokenCookie(token, "production");
    expect(cookie).toMatch(/\bSecure\b/);
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Lax");
  });

  it("Max-Age は 90 日（秒）", () => {
    expect(CART_TOKEN_MAX_AGE_SEC).toBe(90 * 24 * 60 * 60);
  });

  it("Domain は指定があるときだけ付く", () => {
    expect(buildCartTokenCookie(token, "production", "")).not.toContain("Domain=");
    expect(buildCartTokenCookie(token, "production", "example.com")).toContain("Domain=example.com");
  });

  it("値に改行やセミコロンが含まれると例外（ヘッダ注入防止）", () => {
    expect(() => buildSetCookie("x", "a;b", { appEnv: "development", maxAgeSec: 1 })).toThrow();
    expect(() => buildSetCookie("x", "a\r\nSet-Cookie: y=1", { appEnv: "development", maxAgeSec: 1 })).toThrow();
  });
});

describe("readCookie", () => {
  it("Cookie ヘッダから名前で値を取り出す", () => {
    expect(readCookie("a=1; cart_token=tok_123; b=2", "cart_token")).toBe("tok_123");
    expect(readCookie("a=1", "cart_token")).toBeNull();
    expect(readCookie(null, "cart_token")).toBeNull();
  });
});
