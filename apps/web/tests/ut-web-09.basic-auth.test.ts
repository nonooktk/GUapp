import { describe, expect, it } from "vitest";
import {
  BasicAuthConfigError,
  parseBasicAuthConfig,
  verifyBasicAuthHeader,
} from "@/lib/basic-auth";

// テスト設計書 UT-WEB-09: Basic 認証（公開追補 設計仕様書 7 章・DS-DEC-49）
// レビュワー限定公開のための入口保護。両方未設定なら認証なし（ローカル開発を妨げない）、
// 片方だけ設定は起動時か初回で失敗させる、比較は時間一定の比較、というのが設計判断。

describe("UT-WEB-09 parseBasicAuthConfig", () => {
  it("BASIC_AUTH_USER・BASIC_AUTH_PASSWORD が両方未設定なら null（認証なし）", () => {
    expect(parseBasicAuthConfig({})).toBeNull();
  });

  it("両方が空文字でも null（未設定として扱う）", () => {
    expect(parseBasicAuthConfig({ BASIC_AUTH_USER: "", BASIC_AUTH_PASSWORD: "" })).toBeNull();
  });

  it("BASIC_AUTH_USER のみ設定は BasicAuthConfigError", () => {
    expect(() => parseBasicAuthConfig({ BASIC_AUTH_USER: "reviewer" })).toThrow(BasicAuthConfigError);
  });

  it("BASIC_AUTH_PASSWORD のみ設定は BasicAuthConfigError", () => {
    expect(() =>
      parseBasicAuthConfig({ BASIC_AUTH_PASSWORD: "pw" }), // pragma: allowlist secret
    ).toThrow(BasicAuthConfigError);
  });

  it("両方設定されていれば {user, password} を返す", () => {
    expect(
      parseBasicAuthConfig({ BASIC_AUTH_USER: "reviewer", BASIC_AUTH_PASSWORD: "s3cret" }), // pragma: allowlist secret gitleaks:allow
    ).toEqual({ user: "reviewer", password: "s3cret" }); // pragma: allowlist secret gitleaks:allow
  });

  it("前後空白は無視して片方だけ判定しない（空白のみは未設定扱い）", () => {
    expect(parseBasicAuthConfig({ BASIC_AUTH_USER: "  ", BASIC_AUTH_PASSWORD: "  " })).toBeNull();
  });
});

function basicHeader(user: string, password: string): string {
  return `Basic ${Buffer.from(`${user}:${password}`, "utf-8").toString("base64")}`;
}

describe("UT-WEB-09 verifyBasicAuthHeader", () => {
  const USER = "reviewer";
  const PASSWORD = "s3cret-demo"; // pragma: allowlist secret // gitleaks:allow

  it("Authorization ヘッダが無ければ false", () => {
    expect(verifyBasicAuthHeader(null, USER, PASSWORD)).toBe(false);
    expect(verifyBasicAuthHeader(undefined, USER, PASSWORD)).toBe(false);
  });

  it("スキームが Basic でなければ false", () => {
    expect(verifyBasicAuthHeader("Bearer abc123", USER, PASSWORD)).toBe(false);
  });

  it("正しい ID・パスワードなら true", () => {
    expect(verifyBasicAuthHeader(basicHeader(USER, PASSWORD), USER, PASSWORD)).toBe(true);
  });

  it("scheme は大文字小文字を無視する（RFC 7617）", () => {
    const header = `basic ${Buffer.from(`${USER}:${PASSWORD}`, "utf-8").toString("base64")}`;
    expect(verifyBasicAuthHeader(header, USER, PASSWORD)).toBe(true);
  });

  it("パスワードが誤りなら false", () => {
    expect(verifyBasicAuthHeader(basicHeader(USER, "wrong"), USER, PASSWORD)).toBe(false);
  });

  it("ID が誤りなら false", () => {
    expect(verifyBasicAuthHeader(basicHeader("someone-else", PASSWORD), USER, PASSWORD)).toBe(false);
  });

  it("base64 でないなど不正な値は例外を投げず false", () => {
    expect(verifyBasicAuthHeader("Basic ###not-base64###", USER, PASSWORD)).toBe(false);
  });

  it("コロンを含むパスワード（先頭のコロンだけで分割する）", () => {
    const pw = "pa:ss:word"; // pragma: allowlist secret
    expect(verifyBasicAuthHeader(basicHeader(USER, pw), USER, pw)).toBe(true);
  });

  it("user:password の区切りが無いデコード結果は false", () => {
    const header = `Basic ${Buffer.from("no-colon-here", "utf-8").toString("base64")}`;
    expect(verifyBasicAuthHeader(header, USER, PASSWORD)).toBe(false);
  });
});
