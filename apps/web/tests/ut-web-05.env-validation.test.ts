import { describe, expect, it } from "vitest";
import { EnvValidationError, findLeakedPublicSecretKeys, validateEnv } from "@/lib/env-validation";

// テスト設計書 UT-WEB-05: 環境変数ローダー（設計仕様書 7.2・DS-DEC-13）
const validEnv = {
  API_BASE_URL: "http://127.0.0.1:8000/",
  INTERNAL_TOKEN: "dummy-token",
  IMAGE_BASE_URL: "http://localhost:3000/images",
  SESSION_COOKIE_DOMAIN: "",
  APP_ENV: "development",
};

describe("UT-WEB-05 validateEnv", () => {
  it("NEXT_PUBLIC_INTERNAL_TOKEN を含む env は EnvValidationError で拒否される", () => {
    const env = { ...validEnv, NEXT_PUBLIC_INTERNAL_TOKEN: "leaked" };
    expect(() => validateEnv(env)).toThrow(EnvValidationError);
    expect(() => validateEnv(env)).toThrow(/NEXT_PUBLIC_INTERNAL_TOKEN/);
  });

  it.each(["NEXT_PUBLIC_DATABASE_URL", "NEXT_PUBLIC_STRIPE_SECRET", "NEXT_PUBLIC_DB_PASSWORD", "NEXT_PUBLIC_API_KEY"])(
    "%s も秘密名として拒否される",
    (key) => {
      expect(() => validateEnv({ ...validEnv, [key]: "x" })).toThrow(EnvValidationError);
    },
  );

  it("秘密名を含まない NEXT_PUBLIC_ 変数は許可される", () => {
    expect(() => validateEnv({ ...validEnv, NEXT_PUBLIC_SITE_NAME: "GU" })).not.toThrow();
  });

  it("NEXT_PUBLIC_ が付かない INTERNAL_TOKEN は拒否されない（サーバー側の正しい置き場）", () => {
    expect(findLeakedPublicSecretKeys(validEnv)).toEqual([]);
  });

  it("秘密名を含まなければ通り、末尾スラッシュを除いた値が返る", () => {
    const result = validateEnv(validEnv);
    expect(result.API_BASE_URL).toBe("http://127.0.0.1:8000");
    expect(result.INTERNAL_TOKEN).toBe("dummy-token");
    expect(result.APP_ENV).toBe("development");
    expect(result.SESSION_COOKIE_DOMAIN).toBe("");
  });

  it.each(["API_BASE_URL", "INTERNAL_TOKEN", "IMAGE_BASE_URL"])("必須の %s が欠落していると例外", (key) => {
    const env: Record<string, string | undefined> = { ...validEnv };
    delete env[key];
    expect(() => validateEnv(env)).toThrow(new RegExp(key));
  });

  it("必須が空文字でも例外", () => {
    expect(() => validateEnv({ ...validEnv, INTERNAL_TOKEN: "   " })).toThrow(EnvValidationError);
  });

  it("APP_ENV 未設定は development になる", () => {
    const env: Record<string, string | undefined> = { ...validEnv };
    delete env.APP_ENV;
    expect(validateEnv(env).APP_ENV).toBe("development");
  });

  it("APP_ENV が列挙外なら例外", () => {
    expect(() => validateEnv({ ...validEnv, APP_ENV: "staging" })).toThrow(EnvValidationError);
  });
});
