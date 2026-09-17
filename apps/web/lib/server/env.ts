import "server-only";

import { validateEnv, type WebEnv } from "@/lib/env-validation";

/**
 * サーバー側の環境変数ローダー（設計仕様書 7.2・DS-DEC-13）。
 * `server-only` により、クライアントコンポーネントから import するとビルドが失敗する。
 * 検証ルールは lib/env-validation.ts の validateEnv（純粋関数）に置き、ここでは process.env を渡すだけ。
 */

let cached: WebEnv | null = null;

/** 検証済みの環境変数を返す。初回呼び出しで検証し、失敗すれば例外（起動時拒否） */
export function getEnv(): WebEnv {
  if (cached === null) {
    cached = validateEnv(process.env);
  }
  return cached;
}
