import { describe, expect, it } from "vitest";
import { isOrderNumber, lookupErrorMessage, ORDER_MESSAGES, routeOrderError } from "@/lib/order-errors";

// 設計仕様書 3.2・6.8・4.5 と Wave 2 の API 申し送り（クロミ）の「応答 → 戻し先」対応表を全行検証する
describe("routeOrderError", () => {
  it("400 validation_error → SCR-005 の該当項目（fields をそのまま持ち帰る）", () => {
    const fields = [{ name: "ship_postal_code", reason: "format" }];
    expect(routeOrderError(400, { code: "validation_error", fields })).toEqual({
      kind: "field_errors",
      fields,
      message: ORDER_MESSAGES.validation,
    });
  });

  it("404 not_found → カート画面へ（Cookie 無効）", () => {
    expect(routeOrderError(404, { code: "not_found" })).toEqual({ kind: "cart", message: ORDER_MESSAGES.cartInvalid, variantIds: [] });
  });

  it("409 out_of_stock {items} → カート画面へ、該当 variant_id を強調（数値・オブジェクトの両形）", () => {
    expect(routeOrderError(409, { code: "out_of_stock", items: [3, 5] })).toEqual({
      kind: "cart",
      message: ORDER_MESSAGES.outOfStock,
      variantIds: [3, 5],
    });
    expect(routeOrderError(409, { code: "out_of_stock", items: [{ variant_id: 7 }] })).toMatchObject({ variantIds: [7] });
  });

  it("409 price_changed {amounts} → SCR-005 へ戻し、prepare を呼び直す印", () => {
    expect(routeOrderError(409, { code: "price_changed", amounts: { subtotal: 1, shipping_fee: 2, total: 3 } })).toEqual({
      kind: "checkout",
      message: ORDER_MESSAGES.priceChanged,
      focus: "form",
      refetchPrepare: true,
    });
  });

  it("409 payment_failed {order_number} → SCR-005 の支払い方法へ、prepare を呼び直す印", () => {
    expect(routeOrderError(409, { code: "payment_failed", order_number: "GU-260918-ABCDEFGH" })).toEqual({
      kind: "checkout",
      message: ORDER_MESSAGES.paymentFailed,
      focus: "payment",
      refetchPrepare: true,
    });
  });

  it("409 already_ordered {order_number} → 完了画面に既存の番号（2 タブ）。番号が無ければカートへ", () => {
    expect(routeOrderError(409, { code: "already_ordered", order_number: "GU-260918-ABCDEFGH" })).toEqual({
      kind: "complete",
      orderNumber: "GU-260918-ABCDEFGH",
      message: ORDER_MESSAGES.alreadyOrdered,
    });
    expect(routeOrderError(409, { code: "already_ordered" })).toMatchObject({ kind: "cart" });
  });

  it("409 empty_cart → カート画面へ", () => {
    expect(routeOrderError(409, { code: "empty_cart" })).toEqual({ kind: "cart", message: ORDER_MESSAGES.emptyCart, variantIds: [] });
  });

  it("422 unsupported_value → その場で汎用トースト", () => {
    expect(routeOrderError(422, { code: "unsupported_value", field: "receive_method" })).toEqual({ kind: "stay", message: ORDER_MESSAGES.generic });
  });

  it("403 forbidden（BFF の CSRF）→ 再読み込みの案内", () => {
    expect(routeOrderError(403, { code: "forbidden" })).toEqual({ kind: "stay", message: ORDER_MESSAGES.forbidden });
  });

  it("503 upstream_unavailable・500・本文無し → その場に留まる", () => {
    expect(routeOrderError(503, { code: "upstream_unavailable" })).toEqual({ kind: "stay", message: ORDER_MESSAGES.unavailable });
    expect(routeOrderError(500, { code: "internal_error", message: "処理中にエラーが発生しました" })).toEqual({ kind: "stay", message: ORDER_MESSAGES.generic });
    expect(routeOrderError(0, null)).toEqual({ kind: "stay", message: ORDER_MESSAGES.generic });
  });

  it("未知の 409 は汎用トースト", () => {
    expect(routeOrderError(409, { code: "something_new" })).toEqual({ kind: "stay", message: ORDER_MESSAGES.generic });
  });
});

describe("lookupErrorMessage（注文照会）", () => {
  it("404 は番号・メールを区別しない一括表示、429 は待つ案内", () => {
    expect(lookupErrorMessage(404, { code: "not_found" })).toBe("注文番号かメールアドレスが違います");
    expect(lookupErrorMessage(429, { code: "rate_limited" })).toBe(ORDER_MESSAGES.rateLimited);
    expect(lookupErrorMessage(503, { code: "upstream_unavailable" })).toBe(ORDER_MESSAGES.unavailable);
  });
});

describe("isOrderNumber（GU-YYMMDD-XXXXXXXX。I/O/0/1 を含まない）", () => {
  it("形式判定", () => {
    expect(isOrderNumber("GU-260907-7K3M9Q2X")).toBe(true);
    expect(isOrderNumber("GU-260907-7K3M9Q2I")).toBe(false); // I
    expect(isOrderNumber("GU-260907-7K3M9Q20")).toBe(false); // 0
    expect(isOrderNumber("GU-26090-7K3M9Q2X")).toBe(false);
    expect(isOrderNumber("gu-260907-7K3M9Q2X")).toBe(false);
    expect(isOrderNumber(undefined)).toBe(false);
  });
});
