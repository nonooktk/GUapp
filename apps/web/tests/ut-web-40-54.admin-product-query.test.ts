import { describe, expect, it } from "vitest";
import { buildListHref, parseProductQuery, PRODUCT_Q_MAX_LENGTH } from "@/lib/admin-query";

// テスト設計書 UT-WEB-43（商品一覧の検索条件。DS-SCR-015-1）

describe("UT-WEB-43 商品一覧の検索条件", () => {
  it("既定: すべて・1 ページ目。FastAPI へは page だけ渡す", () => {
    const q = parseProductQuery({});
    expect(q).toMatchObject({ q: "", visibility: "all", stock: "all", page: 1, apiQuery: "page=1", linkParams: {} });
  });

  it("正常な条件は FastAPI のクエリに載る", () => {
    const q = parseProductQuery({ q: "Tシャツ", visibility: "private", stock: "out", page: "3" });
    expect(q.visibility).toBe("private");
    expect(q.stock).toBe("out");
    expect(q.page).toBe(3);
    expect(new URLSearchParams(q.apiQuery).get("q")).toBe("Tシャツ");
    expect(new URLSearchParams(q.apiQuery).get("visibility")).toBe("private");
    expect(new URLSearchParams(q.apiQuery).get("stock")).toBe("out");
    expect(q.linkParams).toEqual({ q: "Tシャツ", visibility: "private", stock: "out" });
  });

  it("visibility・stock の列挙外は既定に戻し、FastAPI へ渡さない", () => {
    const q = parseProductQuery({ visibility: "draft", stock: "low" });
    expect(q.visibility).toBe("all");
    expect(q.stock).toBe("all");
    expect(q.apiQuery).toBe("page=1");
  });

  it("q が 51 文字以上なら 50 文字までに切る（コードポイント単位）", () => {
    const q = parseProductQuery({ q: "あ".repeat(51) });
    expect(Array.from(q.q)).toHaveLength(PRODUCT_Q_MAX_LENGTH);
    const emoji = parseProductQuery({ q: "😀".repeat(60) });
    expect(Array.from(emoji.q)).toHaveLength(PRODUCT_Q_MAX_LENGTH);
  });

  it("q は NFKC 正規化と前後空白の除去（全角英数・全角空白）。LIKE の特殊文字はそのまま渡す（エスケープは FastAPI）", () => {
    expect(parseProductQuery({ q: "　ＡＢＣ１２３　" }).q).toBe("ABC123");
    expect(parseProductQuery({ q: "100%_off\\" }).q).toBe("100%_off\\");
    expect(new URLSearchParams(parseProductQuery({ q: "100%_off" }).apiQuery).get("q")).toBe("100%_off");
  });

  it.each([["0"], ["-1"], ["abc"], ["1.5"], ["1234567"], [""], ["１２"]])("page=%j は 1 に直す", (raw) => {
    expect(parseProductQuery({ page: raw }).page).toBe(1);
  });

  it("page は 6 桁までの 1 以上の整数", () => {
    expect(parseProductQuery({ page: "999999" }).page).toBe(999999);
  });

  it("配列で渡された値は先頭の 1 つだけ使う", () => {
    const q = parseProductQuery({ q: ["a", "b"], visibility: ["public", "private"], page: ["2", "9"] });
    expect(q.q).toBe("a");
    expect(q.visibility).toBe("public");
    expect(q.page).toBe(2);
  });

  it("未知のキー（sort・per_page）は FastAPI へ渡さない", () => {
    const q = parseProductQuery({ sort: "price", per_page: "1000", q: "a" });
    expect(new URLSearchParams(q.apiQuery).has("sort")).toBe(false);
    expect(new URLSearchParams(q.apiQuery).has("per_page")).toBe(false);
  });
});

describe("buildListHref（ページ送りのリンク）", () => {
  it("検索条件を保ち、page は 2 以上のときだけ付ける", () => {
    expect(buildListHref("/admin/products", { q: "a" }, 1)).toBe("/admin/products?q=a");
    expect(buildListHref("/admin/products", { q: "a" }, 3)).toBe("/admin/products?q=a&page=3");
    expect(buildListHref("/admin/products", {}, 1)).toBe("/admin/products");
  });

  it("page が 1 未満・小数・NaN なら 1 に直す", () => {
    expect(buildListHref("/admin/orders", {}, 0)).toBe("/admin/orders");
    expect(buildListHref("/admin/orders", {}, 2.5)).toBe("/admin/orders");
    expect(buildListHref("/admin/orders", {}, Number.NaN)).toBe("/admin/orders");
  });
});
