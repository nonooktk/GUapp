import { describe, expect, it } from "vitest";
import { readCsrfCookie } from "@/lib/client/cart-api";
import { buildCartTokenCookie, buildCsrfTokenCookie } from "@/lib/cookie";
import { CSRF_TOKEN_LENGTH, isCsrfTokenShape, isCsrfValid } from "@/lib/csrf-validation";

// 設計仕様書 7.3（CSRF: Double Submit Cookie）・4.5（403 forbidden）。判定は純粋関数で検証する
const token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow（43 文字の形のダミー。秘密ではない） // pragma: allowlist secret
const other = "ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543210-_ZYXWV"; // gitleaks:allow // pragma: allowlist secret

describe("CSRF isCsrfValid", () => {
  it("Cookie とヘッダが一致すれば通過", () => {
    expect(token).toHaveLength(CSRF_TOKEN_LENGTH);
    expect(isCsrfValid(token, token)).toBe(true);
  });

  it("ヘッダ欠落・Cookie 欠落は拒否", () => {
    expect(isCsrfValid(token, null)).toBe(false);
    expect(isCsrfValid(token, undefined)).toBe(false);
    expect(isCsrfValid(null, token)).toBe(false);
    expect(isCsrfValid(null, null)).toBe(false);
    expect(isCsrfValid("", "")).toBe(false);
  });

  it("不一致は拒否（1 文字違いも）", () => {
    expect(isCsrfValid(token, other)).toBe(false);
    expect(isCsrfValid(token, token.slice(0, -1) + "X")).toBe(false);
  });

  it("形が不正（長さ違い・許可外文字）なら一致していても拒否", () => {
    expect(isCsrfValid("short", "short")).toBe(false);
    const bad = token.slice(0, -1) + "!";
    expect(isCsrfValid(bad, bad)).toBe(false);
    expect(isCsrfTokenShape(token)).toBe(true);
    expect(isCsrfTokenShape(token + "a")).toBe(false);
  });
});

describe("CSRF Cookie の属性", () => {
  it("csrf_token Cookie に HttpOnly が無い（JS が読んでヘッダに載せるため）。SameSite=Lax・Path=/", () => {
    const cookie = buildCsrfTokenCookie(token, "development");
    expect(cookie).toContain(`csrf_token=${token}`);
    expect(cookie).not.toMatch(/\bHttpOnly\b/);
    expect(cookie).toContain("SameSite=Lax");
    expect(cookie).toContain("Path=/");
    expect(cookie).not.toMatch(/\bSecure\b/);
  });

  it("production では Secure が付く", () => {
    expect(buildCsrfTokenCookie(token, "production")).toMatch(/\bSecure\b/);
  });

  it("cart_token Cookie は引き続き HttpOnly（回帰確認）", () => {
    expect(buildCartTokenCookie(token, "development")).toMatch(/\bHttpOnly\b/);
  });
});

describe("readCsrfCookie（クライアント側の document.cookie 読み取り）", () => {
  it("csrf_token を取り出す。形が不正なら null", () => {
    expect(readCsrfCookie(`a=1; csrf_token=${token}; b=2`)).toBe(token);
    expect(readCsrfCookie("a=1")).toBeNull();
    expect(readCsrfCookie("csrf_token=bad")).toBeNull();
  });
});
