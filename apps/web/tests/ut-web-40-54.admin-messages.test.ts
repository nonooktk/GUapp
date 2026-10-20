import { describe, expect, it } from "vitest";
import { adminErrorMessage, adminRangeMessage, formatCurrent, isSessionExpired } from "@/lib/admin-messages";

// テスト設計書 UT-WEB-49（管理画面のエラー文言の対応表。設計仕様書 P2 追補c 6.7）

describe("UT-WEB-49 管理画面のエラー文言", () => {
  it.each([
    [401, { code: "invalid_credentials" }, "ログイン ID またはパスワードが違います"],
    [403, { code: "account_locked" }, "ログインを一時的に止めています。しばらくしてからもう一度お試しください"],
    [429, { code: "rate_limited" }, "試行回数が多すぎます。しばらくしてからもう一度お試しください"],
    [401, { code: "unauthorized" }, "セッションの有効期限が切れました。もう一度ログインしてください"],
    [403, { code: "forbidden" }, "画面を読み込み直してから、もう一度お試しください"],
    [409, { code: "invalid_transition", from: "delivered", to: "preparing" }, "この注文の状態はすでに変わっています。画面を更新しました"],
    [503, { code: "upstream_unavailable" }, "サーバーに接続できません。しばらくしてからもう一度お試しください"],
    [500, { code: "internal_error" }, "サーバーに接続できません。しばらくしてからもう一度お試しください"],
  ])("%i %j → 6.7 の表どおり", (status, body, message) => {
    expect(adminErrorMessage(status, body)).toBe(message);
  });

  it("409 stale_data の文言に current の値が入る（数値・文字列・公開状態）", () => {
    expect(adminErrorMessage(409, { code: "stale_data", field: "stock", current: 3 })).toBe(
      "他の操作で値が変わっていました（現在の値：3）。内容を確認してもう一度保存してください",
    );
    expect(adminErrorMessage(409, { code: "stale_data", field: "tax_rate", current: "0.08" })).toContain("現在の値：0.08");
    expect(adminErrorMessage(409, { code: "stale_data", field: "published", current: true })).toContain("現在の値：公開");
    expect(adminErrorMessage(409, { code: "stale_data", field: "published", current: false })).toContain("現在の値：非公開");
    expect(adminErrorMessage(409, { code: "stale_data", field: "price_incl_tax", current: 12500 })).toContain("現在の値：12,500");
  });

  it("422 は {項目名}は {下限} 以上 {上限} 以下で入力してください。項目名は画面の呼び名にする", () => {
    expect(adminErrorMessage(422, { code: "limit_exceeded", field: "price_incl_tax", limit: 1000000 })).toBe("価格は 1 以上 1,000,000 以下で入力してください");
    expect(adminErrorMessage(422, { code: "unsupported_value", field: "stock" })).toBe("在庫は 0 以上 9,999 以下で入力してください");
    expect(adminErrorMessage(422, { code: "limit_exceeded", field: "tax_rate" })).toBe("消費税率は 0.00 以上 0.30 以下で入力してください");
    expect(adminErrorMessage(422, { code: "limit_exceeded", field: "shipping_fee" })).toBe("送料は 0 以上 5,000 以下で入力してください");
    expect(adminErrorMessage(422, { code: "limit_exceeded", field: "free_shipping_threshold" })).toBe("送料無料の下限は 0 以上 100,000 以下で入力してください");
  });

  it("422 unsupported_value（追跡番号）は「追跡番号を付けられない注文です」。範囲を持たない項目は汎用文言", () => {
    expect(adminErrorMessage(422, { code: "unsupported_value", field: "tracking_number" })).toBe("追跡番号を付けられない注文です");
    expect(adminErrorMessage(422, { code: "unsupported_value", field: "status" })).toBe("処理に失敗しました");
  });

  it("400 validation_error は {項目名}の形式が正しくありません。項目が分からなければ入力内容", () => {
    expect(adminErrorMessage(400, { code: "validation_error", fields: [{ name: "stock", reason: "format" }] })).toBe("在庫の形式が正しくありません");
    expect(adminErrorMessage(400, { code: "validation_error", fields: [{ name: "tax_rate", reason: "format" }] })).toBe("消費税率の形式が正しくありません");
    expect(adminErrorMessage(400, { code: "validation_error" })).toBe("入力内容の形式が正しくありません");
    expect(adminErrorMessage(400, { code: "validation_error", fields: [{ name: "__proto__", reason: "format" }] })).toBe("入力内容の形式が正しくありません");
  });

  it("未知のコードは汎用の文言で、内部のコードを画面に出さない", () => {
    const m = adminErrorMessage(418, { code: "teapot_overflow" });
    expect(m).toBe("処理に失敗しました");
    expect(m).not.toContain("teapot");
    expect(adminErrorMessage(0, null)).toBe("処理に失敗しました");
    expect(adminErrorMessage(400, { code: "bad_response" })).toBe("処理に失敗しました");
  });

  it("isSessionExpired は 401 unauthorized だけ真(ログイン失敗の 401 invalid_credentials は偽)", () => {
    expect(isSessionExpired(401, { code: "unauthorized" })).toBe(true);
    expect(isSessionExpired(401, { code: "invalid_credentials" })).toBe(false);
    expect(isSessionExpired(403, { code: "forbidden" })).toBe(false);
    expect(isSessionExpired(0, null)).toBe(false);
  });

  it("formatCurrent と adminRangeMessage の補助", () => {
    expect(formatCurrent(undefined)).toBe("不明");
    expect(formatCurrent({})).toBe("不明");
    expect(formatCurrent("x".repeat(100)).length).toBe(40);
    expect(adminRangeMessage("name")).toBeNull();
    expect(adminRangeMessage(undefined)).toBeNull();
  });
});
