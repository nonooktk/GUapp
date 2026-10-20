import { describe, expect, it } from "vitest";
import { DEFAULT_NEXT, firstParam, parsePage, safeNext } from "@/lib/safe-next";

// テスト設計書 UT-WEB-14（safeNext。DS-DEC-85）・ST-SEC-52 の土台（オープンリダイレクト対策 C-04）。設計仕様書 6.3
describe("UT-WEB-14 safeNext", () => {
  it.each([
    "//evil.example",
    "/\\evil.example",
    "https://evil.example",
    "http://evil.example/mypage",
    "javascript:alert(1)",
    "/%2F%2Fevil.example",
    "%2F%2Fevil.example",
    "/products/12abc",
    "/products/",
    "/products/12/extra",
    "/products/1234567890123456789", // 19 桁
    "/admin",
    "/mypage/orders/GU-261024-ABCDEFGH",
    "/mypage\n",
    "/mypage%0d%0aSet-Cookie:x=1",
    "mypage",
    "",
    "x".repeat(5000),
    "/" + "a".repeat(5000),
  ])("許可リスト外 %j は /mypage", (raw) => {
    expect(safeNext(raw)).toBe(DEFAULT_NEXT);
    expect(safeNext(raw)).toBe("/mypage");
  });

  it("未指定・文字列でない値は /mypage", () => {
    expect(safeNext(undefined)).toBe("/mypage");
    expect(safeNext(null)).toBe("/mypage");
    expect(safeNext(123)).toBe("/mypage");
    expect(safeNext(["/checkout"])).toBe("/mypage");
  });

  it.each([
    ["/checkout", "/checkout"],
    ["/cart", "/cart"],
    ["/mypage", "/mypage"],
    ["/products/12", "/products/12"],
    ["/mypage?x=1", "/mypage"],
    ["/checkout?a=b#frag", "/checkout"],
    ["/products/12#reviews", "/products/12"],
  ])("許可された %j は %j", (raw, expected) => {
    expect(safeNext(raw)).toBe(expected);
  });

  it("クエリを捨てたあとのパスが許可リストにないなら /mypage（?next= の入れ子を通さない）", () => {
    expect(safeNext("/login?next=//evil.example")).toBe("/mypage");
    expect(safeNext("/?next=/checkout")).toBe("/mypage");
  });
});

describe("firstParam / parsePage", () => {
  it("配列なら先頭、文字列はそのまま、無ければ undefined", () => {
    expect(firstParam(["a", "b"])).toBe("a");
    expect(firstParam("a")).toBe("a");
    expect(firstParam(undefined)).toBeUndefined();
  });

  it("parsePage: 1 以上の整数だけ通し、不正な値は 1", () => {
    expect(parsePage("2")).toBe(2);
    expect(parsePage("120")).toBe(120);
    for (const bad of [undefined, "", "0", "-1", "1.5", "abc", "2abc", "1234567", " 2"]) expect(parsePage(bad)).toBe(1);
  });
});
