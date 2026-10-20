import { describe, expect, it } from "vitest";
import {
  buildSessionCookie,
  buildSessionDeleteCookie,
  readSessionToken,
  SESSION_MAX_AGE_SEC,
} from "@/lib/cookie";

// テスト設計書 UT-WEB-15（sid Cookie の組み立て。DS-DEC-72）・ST-SEC-44 の土台。設計仕様書 7.3
const TOKEN = "newSidBBBB_-0123456789abcdefghijklmnopqrstu"; // gitleaks:allow（Cookie 属性検証用のダミー値）

describe("UT-WEB-15 sid Cookie", () => {
  it("通常値: HttpOnly・SameSite=Lax・Path=/・Max-Age=86400。development は Secure なし", () => {
    const c = buildSessionCookie(TOKEN, "development");
    expect(c).toContain(`sid=${TOKEN}`);
    for (const attr of ["HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=86400"]) expect(c).toContain(attr);
    expect(c).not.toMatch(/\bSecure\b/);
    expect(SESSION_MAX_AGE_SEC).toBe(24 * 60 * 60);
  });

  it("production は Secure が付く。Domain は指定があるときだけ", () => {
    expect(buildSessionCookie(TOKEN, "production")).toMatch(/\bSecure\b/);
    expect(buildSessionCookie(TOKEN, "production")).not.toContain("Domain=");
    expect(buildSessionCookie(TOKEN, "production", "example.com")).toContain("Domain=example.com");
  });

  it("削除用: 値が空・Max-Age=0。属性（HttpOnly・Path・Domain・Secure）は発行時と同じ", () => {
    const c = buildSessionDeleteCookie("production", "example.com");
    expect(c).toMatch(/^sid=;/);
    for (const attr of ["Max-Age=0", "HttpOnly", "SameSite=Lax", "Path=/", "Domain=example.com", "Secure"]) expect(c).toContain(attr);
  });

  it("使えない文字（改行・; など）を含む値は例外（ヘッダ注入を防ぐ）", () => {
    expect(() => buildSessionCookie("a;b", "development")).toThrow();
    expect(() => buildSessionCookie("a\r\nSet-Cookie: x=1", "development")).toThrow();
  });

  it("readSessionToken: 43 文字の base64url だけを返し、それ以外は null（解釈はしない）", () => {
    expect(readSessionToken(`a=1; sid=${TOKEN}; b=2`)).toBe(TOKEN);
    expect(readSessionToken("sid=short")).toBeNull();
    expect(readSessionToken(`sid=${TOKEN}x`)).toBeNull();
    expect(readSessionToken(`sid=${TOKEN.slice(0, 42)}!`)).toBeNull();
    expect(readSessionToken("a=1")).toBeNull();
    expect(readSessionToken(null)).toBeNull();
  });
});
