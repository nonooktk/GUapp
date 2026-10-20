import { describe, expect, it } from "vitest";
import { AUTH_MESSAGES, authErrorMessage, mapRegisterFieldErrors } from "@/lib/auth-messages";

// テスト設計書 UT-WEB-25（認証系のエラー文言の対応表）。設計仕様書 6.3・4.9
describe("UT-WEB-25 認証系のエラー文言", () => {
  it.each([
    [401, { code: "invalid_credentials" }, "メールアドレスまたはパスワードが違います"],
    [403, { code: "account_locked" }, "ログインを一時的に止めています。しばらくしてからもう一度お試しください"],
    [429, { code: "rate_limited" }, "試行が多すぎます。しばらくしてからお試しください"],
    [422, { code: "weak_password", field: "password" }, "よくあるパスワードやメールアドレスと同じ値は使えません"],
    [422, { code: "unsupported_value", field: "email" }, "このサイトでは使えないメールアドレスです"],
    [404, { code: "not_found" }, "リンクが無効か、期限が切れています"],
    [400, { code: "validation_error" }, "入力内容を確認してください"],
    [503, { code: "upstream_unavailable" }, "接続できません"],
    [403, { code: "forbidden" }, "ページを再読み込みしてからもう一度お試しください"],
  ])("%i %j → %s", (status, body, message) => {
    expect(authErrorMessage(status, body)).toBe(message);
  });

  it("未知のコード・本文なし・ネットワーク断は汎用の文言で、内部のコードを出さない", () => {
    for (const [status, body] of [
      [500, { code: "internal_error", message: "boom" }],
      [418, { code: "teapot" }],
      [502, { code: "upstream_error" }],
      [0, null],
    ] as const) {
      const msg = authErrorMessage(status, body);
      expect(msg).toBe(AUTH_MESSAGES.generic);
      expect(msg).not.toMatch(/internal_error|teapot|upstream_error/);
    }
  });

  it("401 のログイン失敗は、メールとパスワードのどちらが違うかを書かない（ユーザー列挙の防止）", () => {
    expect(authErrorMessage(401, { code: "invalid_credentials" })).not.toMatch(/登録|存在|見つかり/);
  });

  it("mapRegisterFieldErrors: 既知の項目だけを項目ごとの固定文にし、未知の項目名は捨てる", () => {
    const errs = mapRegisterFieldErrors([
      { name: "email", reason: "format" },
      { name: "password", reason: "too_short" },
      { name: "__proto__", reason: "x" },
      { name: "role", reason: "x" },
      null,
      "x",
    ]);
    expect(Object.keys(errs).sort()).toEqual(["email", "password"]);
    expect(mapRegisterFieldErrors("not-an-array")).toEqual({});
  });
});
