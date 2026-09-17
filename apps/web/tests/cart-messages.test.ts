import { describe, expect, it } from "vitest";
import { cartErrorMessage, stockWarning } from "@/lib/cart-messages";
import { imageUrl } from "@/lib/image";

// 設計仕様書 4.5 のエラー本文 → 利用者向け文言（409／422 の出し分け）と 6.6 の在庫警告文
describe("cartErrorMessage", () => {
  it("409 out_of_stock と 422 limit_exceeded（quantity=10 / cart=50）を出し分ける", () => {
    expect(cartErrorMessage(409, { code: "out_of_stock", items: [] })).toBe("在庫切れのため追加できません");
    expect(cartErrorMessage(422, { code: "limit_exceeded", field: "quantity", limit: 10 })).toBe("1 つの商品は 10 点までです");
    expect(cartErrorMessage(422, { code: "limit_exceeded", field: "quantity", limit: 50 })).toBe(
      "カートに入れられるのは合計 50 点までです",
    );
  });

  it("403・503・500・不明コードは固定文言（内部情報を出さない）", () => {
    expect(cartErrorMessage(403, { code: "forbidden" })).toMatch(/再読み込み/);
    expect(cartErrorMessage(503, { code: "upstream_unavailable" })).toMatch(/接続できません/);
    expect(cartErrorMessage(500, { code: "internal_error", message: "x" })).toBe("処理中にエラーが発生しました");
    expect(cartErrorMessage(418, null)).toBe("操作に失敗しました");
  });
});

describe("stockWarning", () => {
  it("ok は null、insufficient / out_of_stock は設計書 6.6 の文言", () => {
    expect(stockWarning("ok")).toBeNull();
    expect(stockWarning("insufficient")).toBe("在庫が不足しています");
    expect(stockWarning("out_of_stock")).toBe("在庫切れのため購入できません");
  });
});

describe("imageUrl", () => {
  it("IMAGE_BASE_URL + / + image_path。重複スラッシュを作らない", () => {
    expect(imageUrl("http://localhost:3000", "products/001/1.jpg")).toBe("http://localhost:3000/products/001/1.jpg");
    expect(imageUrl("http://localhost:3000/", "/products/001/1.jpg")).toBe("http://localhost:3000/products/001/1.jpg");
    expect(imageUrl("http://localhost:3000", null)).toBeNull();
  });
});
