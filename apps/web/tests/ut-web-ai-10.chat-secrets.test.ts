import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { EnvValidationError, findLeakedPublicSecretKeys, validateEnv } from "@/lib/env-validation";

// テスト設計書 UT-WEB-AI-10: 秘密の混入（設計仕様書 P2 追補d 7.2）。
// NEXT_PUBLIC_OPENAI_API_KEY は起動時の検証で拒否される。web のソースに OPENAI_API_KEY の参照が無い（web は api のキーを知らない）。

const BASE_ENV = {
  API_BASE_URL: "http://fastapi.test:8000",
  INTERNAL_TOKEN: "dummy-internal-token", // gitleaks:allow（テスト用ダミー）
  IMAGE_BASE_URL: "http://localhost:3000",
};

function listSources(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === ".next" || name === "tests") continue;
    const abs = path.join(dir, name);
    if (statSync(abs).isDirectory()) out.push(...listSources(abs));
    else if (/\.(tsx?|mts|mjs|css|json)$/.test(name) && name !== "pnpm-lock.yaml") out.push(abs);
  }
  return out;
}

describe("UT-WEB-AI-10 秘密の混入", () => {
  it("NEXT_PUBLIC_OPENAI_API_KEY は findLeakedPublicSecretKeys に検出され、validateEnv が失敗する", () => {
    const env = { ...BASE_ENV, NEXT_PUBLIC_OPENAI_API_KEY: "sk-test" }; // gitleaks:allow // pragma: allowlist secret
    expect(findLeakedPublicSecretKeys(env)).toEqual(["NEXT_PUBLIC_OPENAI_API_KEY"]);
    expect(() => validateEnv(env)).toThrow(EnvValidationError);
    expect(findLeakedPublicSecretKeys({ NEXT_PUBLIC_OPENAI_MODEL: "x" })).toEqual([]); // 秘密の名前を含まない変数は対象外
  });

  it("web のソース（tests 以外）に OPENAI_API_KEY の参照が 0 件", () => {
    const root = path.resolve(import.meta.dirname, "..");
    const files = ["app", "components", "lib", "scripts"].flatMap((d) => listSources(path.join(root, d)));
    files.push(path.join(root, "proxy.ts"));
    expect(files.length).toBeGreaterThan(50);
    for (const f of files) {
      const text = readFileSync(f, "utf8");
      expect(text, f).not.toMatch(/OPENAI_API_KEY/);
      expect(text, f).not.toMatch(/\bsk-[A-Za-z0-9_-]{20,}/);
    }
  });
});
