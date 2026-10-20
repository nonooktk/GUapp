import { describe, expect, it } from "vitest";
import {
  ADMIN_SESSION_COOKIE,
  buildAdminSessionCookie,
  buildAdminSessionDeleteCookie,
  isAdminSessionTokenShape,
  readAdminSessionToken,
} from "@/lib/admin-cookie";
import { buildSessionCookie } from "@/lib/cookie";
import { ASID_NEW } from "./helpers/admin";

// テスト設計書 UT-WEB-40（asid Cookie の組み立て。DS-DEC-108）・ST-SEC-83 の自動化できる部分

describe("UT-WEB-40 asid Cookie の組み立て", () => {
  it("通常値: HttpOnly・SameSite=Strict・Path=/admin・Max-Age=28800。development では Secure を付けない", () => {
    const c = buildAdminSessionCookie(ASID_NEW, "development");
    expect(c).toBe(`asid=${ASID_NEW}; Path=/admin; Max-Age=28800; HttpOnly; SameSite=Strict`);
    expect(c).not.toMatch(/\bSecure\b/);
  });

  it("production の設定: Secure が付く。Domain は指定があるときだけ付く", () => {
    const c = buildAdminSessionCookie(ASID_NEW, "production", "shop.example.test");
    for (const attr of ["HttpOnly", "SameSite=Strict", "Path=/admin", "Max-Age=28800", "Secure", "Domain=shop.example.test"]) {
      expect(c).toContain(attr);
    }
    expect(buildAdminSessionCookie(ASID_NEW, "production")).not.toContain("Domain=");
  });

  it("削除用: 値が空・Max-Age=0・Path=/admin（Path が違うと消えないので同じにする）", () => {
    const c = buildAdminSessionDeleteCookie("production");
    expect(c).toMatch(/^asid=; /);
    for (const attr of ["Max-Age=0", "Path=/admin", "HttpOnly", "SameSite=Strict", "Secure"]) expect(c).toContain(attr);
  });

  it("使えない文字（改行・; ・空白）を含む値は例外（ヘッダ注入を防ぐ）", () => {
    expect(() => buildAdminSessionCookie("abc\r\nSet-Cookie: x=1", "development")).toThrow();
    expect(() => buildAdminSessionCookie("abc;Path=/", "development")).toThrow();
    expect(() => buildAdminSessionCookie("a b", "development")).toThrow();
  });

  it("会員の sid の組み立て（UT-WEB-15）は変わらない: Path=/・SameSite=Lax・86400", () => {
    const c = buildSessionCookie("x".repeat(43), "development");
    expect(c).toContain("Path=/;");
    expect(c).toContain("SameSite=Lax");
    expect(c).toContain("Max-Age=86400");
  });

  it("Cookie 名は asid（会員の sid と別）", () => {
    expect(ADMIN_SESSION_COOKIE).toBe("asid");
  });
});

describe("readAdminSessionToken（形が違う値はセッションなし）", () => {
  it("43 文字の base64url だけを返す", () => {
    expect(readAdminSessionToken(`a=1; asid=${ASID_NEW}; b=2`)).toBe(ASID_NEW);
    expect(readAdminSessionToken("asid=short")).toBeNull();
    expect(readAdminSessionToken(`asid=${ASID_NEW}x`)).toBeNull();
    expect(readAdminSessionToken(`asid=${ASID_NEW.slice(0, 42)}!`)).toBeNull();
    expect(readAdminSessionToken("")).toBeNull();
    expect(readAdminSessionToken(null)).toBeNull();
  });

  it("会員の sid だけがあっても asid としては読まない（Cookie の取り違えをしない）", () => {
    expect(readAdminSessionToken(`sid=${ASID_NEW}`)).toBeNull();
  });

  it("isAdminSessionTokenShape", () => {
    expect(isAdminSessionTokenShape(ASID_NEW)).toBe(true);
    expect(isAdminSessionTokenShape("x")).toBe(false);
    expect(isAdminSessionTokenShape(null)).toBe(false);
  });
});
