import { describe, expect, it } from "vitest";
import {
  ADDRESS_SEPARATOR,
  digitsOnly,
  EMPTY_CHECKOUT_FORM,
  joinShipAddress,
  mapServerFieldErrors,
  MESSAGES,
  normalizeDigitsInput,
  PREFECTURES,
  toShippingBody,
  validateCheckoutForm,
  type CheckoutFormValues,
} from "@/lib/checkout-validation";

// 設計仕様書 4.4 DS-PRC-014-1 の入力形式表（ST-F013-02・UT-VAL 相当）。サーバーと同じ規則をクライアントでも検査する
const valid: CheckoutFormValues = {
  name: "テスト 太郎",
  postal: "100-0001",
  prefecture: "東京都",
  city: "千代田区",
  street: "千代田1-1",
  building: "テストビル 101",
  phone: "090-1234-5678",
  email: "test@example.com",
};

describe("validateCheckoutForm", () => {
  it("テスト用のダミー配送先はエラー無し", () => {
    expect(validateCheckoutForm(valid)).toEqual({});
  });

  it("全項目空なら必須（建物以外）がエラー", () => {
    const errs = validateCheckoutForm(EMPTY_CHECKOUT_FORM);
    expect(Object.keys(errs).sort()).toEqual(["city", "email", "name", "phone", "postal", "prefecture", "street"]);
    expect(errs.building).toBeUndefined();
  });

  it("郵便番号: 6 桁・8 桁は不可、100-0001（ハイフン付き 7 桁）は可", () => {
    expect(validateCheckoutForm({ ...valid, postal: "100000" }).postal).toBe(MESSAGES.postal);
    expect(validateCheckoutForm({ ...valid, postal: "10000012" }).postal).toBe(MESSAGES.postal);
    expect(validateCheckoutForm({ ...valid, postal: "100-0001" }).postal).toBeUndefined();
    expect(validateCheckoutForm({ ...valid, postal: "1000001" }).postal).toBeUndefined();
  });

  it("電話: 英字は不可、10 桁・11 桁は可、9 桁・12 桁は不可", () => {
    expect(validateCheckoutForm({ ...valid, phone: "0312345abc" }).phone).toBe(MESSAGES.phone); // pragma: allowlist secret // gitleaks:allow
    expect(validateCheckoutForm({ ...valid, phone: "03-1234-5678" }).phone).toBeUndefined();
    expect(validateCheckoutForm({ ...valid, phone: "090-1234-5678" }).phone).toBeUndefined();
    expect(validateCheckoutForm({ ...valid, phone: "031234567" }).phone).toBe(MESSAGES.phone);
    expect(validateCheckoutForm({ ...valid, phone: "090123456789" }).phone).toBe(MESSAGES.phone);
  });

  it("メール: @ 無し・ドット無しドメイン・空白入りは不可", () => {
    expect(validateCheckoutForm({ ...valid, email: "test.example.com" }).email).toBe(MESSAGES.email);
    expect(validateCheckoutForm({ ...valid, email: "test@localhost" }).email).toBe(MESSAGES.email);
    expect(validateCheckoutForm({ ...valid, email: "te st@example.com" }).email).toBe(MESSAGES.email);
    expect(validateCheckoutForm({ ...valid, email: "test@example.com" }).email).toBeUndefined();
  });

  it("氏名: 50 文字は可、51 文字は不可（コードポイントで数える）", () => {
    expect(validateCheckoutForm({ ...valid, name: "あ".repeat(50) }).name).toBeUndefined();
    expect(validateCheckoutForm({ ...valid, name: "あ".repeat(51) }).name).toBe(MESSAGES.name_too_long);
    expect(validateCheckoutForm({ ...valid, name: "   " }).name).toBe(MESSAGES.required);
  });

  it("住所: 結合後 200 文字は可、201 文字は不可（番地の欄に出す）", () => {
    // 東京都(3) + 全角スペース(1) + 千代田区(4) + 全角スペース(1) = 9 → 番地 191 文字で 200
    const ok = { ...valid, building: "", street: "1".repeat(191) };
    expect(joinShipAddress(ok)).toHaveLength(200);
    expect(validateCheckoutForm(ok).street).toBeUndefined();
    const ng = { ...ok, street: "1".repeat(192) };
    expect(joinShipAddress(ng)).toHaveLength(201);
    expect(validateCheckoutForm(ng).street).toBe(MESSAGES.address_too_long);
  });

  it("都道府県は 47 件のリスト外なら不可", () => {
    expect(PREFECTURES).toHaveLength(47);
    expect(validateCheckoutForm({ ...valid, prefecture: "江戸" }).prefecture).toBe(MESSAGES.select);
  });
});

describe("正規化・結合", () => {
  it("normalizeDigitsInput: 全角数字・全角ハイフンを半角に、数字とハイフン以外を除去", () => {
    expect(normalizeDigitsInput("１００−０００１")).toBe("100-0001");
    expect(normalizeDigitsInput("090 1234 abc 5678")).toBe("09012345678");
  });

  it("digitsOnly: ハイフンも除いた数字だけ", () => {
    expect(digitsOnly("100-0001")).toBe("1000001");
    expect(digitsOnly("090-1234-5678")).toBe("09012345678");
  });

  it("joinShipAddress: 都道府県・市区町村・番地・建物 を全角スペースで結合。建物が空なら落とす", () => {
    expect(joinShipAddress(valid)).toBe(["東京都", "千代田区", "千代田1-1", "テストビル 101"].join(ADDRESS_SEPARATOR));
    expect(joinShipAddress({ ...valid, building: "  " })).toBe(["東京都", "千代田区", "千代田1-1"].join(ADDRESS_SEPARATOR));
  });

  it("toShippingBody: 送信値は数字のみの郵便番号・電話、trim した氏名・メール", () => {
    expect(toShippingBody({ ...valid, name: " テスト 太郎 ", email: " test@example.com " })).toEqual({
      ship_name: "テスト 太郎",
      ship_postal_code: "1000001",
      ship_address: "東京都　千代田区　千代田1-1　テストビル 101",
      ship_phone: "09012345678",
      guest_email: "test@example.com",
    });
  });
});

describe("mapServerFieldErrors（400 validation_error の fields → 項目）", () => {
  it("ship_* / guest_email をフォーム項目に対応付け、reason ごとの文言にする", () => {
    const errs = mapServerFieldErrors([
      { name: "ship_postal_code", reason: "format" },
      { name: "guest_email", reason: "format" },
      { name: "ship_name", reason: "too_long" },
      { name: "ship_address", reason: "too_long" },
      { name: "ship_phone", reason: "required" },
    ]);
    expect(errs).toEqual({
      postal: MESSAGES.postal,
      email: MESSAGES.email,
      name: "文字数が多すぎます",
      street: "文字数が多すぎます",
      phone: MESSAGES.required,
    });
  });

  it("未知の項目名・壊れた形は捨てる", () => {
    expect(mapServerFieldErrors([{ name: "idempotency_key", reason: "format" }, "x", null])).toEqual({});
    expect(mapServerFieldErrors("not an array")).toEqual({});
  });
});
