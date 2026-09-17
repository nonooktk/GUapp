/**
 * 環境変数の検証ルール（純粋関数）。設計仕様書 7.2・DS-DEC-13、テスト UT-WEB-05。
 *
 * 秘密を触らない純粋関数なので `server-only` を付けず、Vitest から直接テストできる。
 * 実際に process.env を読む処理は lib/server/env.ts に置く（そちらは server-only）。
 */

export const APP_ENVS = ["development", "test", "production"] as const;
export type AppEnv = (typeof APP_ENVS)[number];

/** 必須の環境変数（無ければ起動時に例外） */
export const REQUIRED_KEYS = ["API_BASE_URL", "INTERNAL_TOKEN", "IMAGE_BASE_URL"] as const;

/** `NEXT_PUBLIC_` 付き変数の名前に含まれていたら拒否する語（秘密の名前） */
export const SECRET_NAME_PATTERNS = ["TOKEN", "SECRET", "PASSWORD", "DATABASE_URL", "API_KEY"] as const;

export interface WebEnv {
  API_BASE_URL: string;
  INTERNAL_TOKEN: string;
  IMAGE_BASE_URL: string;
  /** Cookie の Domain 属性。ローカルは空（属性を付けない） */
  SESSION_COOKIE_DOMAIN: string;
  APP_ENV: AppEnv;
}

export class EnvValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EnvValidationError";
  }
}

/** `NEXT_PUBLIC_` で始まり、かつ秘密の名前を含むキーを返す */
export function findLeakedPublicSecretKeys(env: Record<string, string | undefined>): string[] {
  return Object.keys(env).filter((key) => {
    if (!key.startsWith("NEXT_PUBLIC_")) return false;
    const upper = key.toUpperCase();
    return SECRET_NAME_PATTERNS.some((pattern) => upper.includes(pattern));
  });
}

/**
 * 環境変数を検証して型付きの設定を返す。問題があれば EnvValidationError を投げる。
 * - `NEXT_PUBLIC_*` に秘密の名前があれば拒否（UT-WEB-05）
 * - 必須キーの欠落・空文字を拒否
 * - APP_ENV は development | test | production のみ（未設定は development）
 */
export function validateEnv(env: Record<string, string | undefined>): WebEnv {
  const leaked = findLeakedPublicSecretKeys(env);
  if (leaked.length > 0) {
    throw new EnvValidationError(
      `秘密を NEXT_PUBLIC_ 変数に置くことはできません（クライアントへ公開されます）: ${leaked.join(", ")}`,
    );
  }

  const missing = REQUIRED_KEYS.filter((key) => (env[key] ?? "").trim() === "");
  if (missing.length > 0) {
    throw new EnvValidationError(`必須の環境変数が未設定です: ${missing.join(", ")}`);
  }

  const appEnvRaw = env.APP_ENV?.trim() || "development";
  if (!(APP_ENVS as readonly string[]).includes(appEnvRaw)) {
    throw new EnvValidationError(
      `APP_ENV は ${APP_ENVS.join(" | ")} のいずれかにしてください（現在: ${appEnvRaw}）`,
    );
  }

  return {
    API_BASE_URL: (env.API_BASE_URL ?? "").trim().replace(/\/+$/, ""),
    INTERNAL_TOKEN: (env.INTERNAL_TOKEN ?? "").trim(),
    IMAGE_BASE_URL: (env.IMAGE_BASE_URL ?? "").trim().replace(/\/+$/, ""),
    SESSION_COOKIE_DOMAIN: env.SESSION_COOKIE_DOMAIN?.trim() ?? "",
    APP_ENV: appEnvRaw as AppEnv,
  };
}
