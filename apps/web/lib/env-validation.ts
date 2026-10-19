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

/** 回数制限の既定値（IP ごと・60 秒の固定窓。セキュリティ強化 S1） */
export const DEFAULT_RATE_LIMIT_API_PER_MIN = 120;
export const DEFAULT_RATE_LIMIT_PAGE_PER_MIN = 600;

export interface WebEnv {
  API_BASE_URL: string;
  INTERNAL_TOKEN: string;
  IMAGE_BASE_URL: string;
  /** Cookie の Domain 属性。ローカルは空（属性を付けない） */
  SESSION_COOKIE_DOMAIN: string;
  APP_ENV: AppEnv;
  /** 信頼するプロキシのホップ数（X-Forwarded-For を右から数える位置。未設定は 0＝利用者送信の XFF を使わない） */
  TRUSTED_PROXY_HOPS: number;
  /** `/api/*`（BFF）の 1 IP あたり 1 分の上限。未設定は 120 */
  RATE_LIMIT_API_PER_MIN: number;
  /** ページ・RSC・prefetch の 1 IP あたり 1 分の上限。未設定は 600 */
  RATE_LIMIT_PAGE_PER_MIN: number;
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
 * 任意の環境変数 TRUSTED_PROXY_HOPS を読む。未設定・空は 0（利用者送信の X-Forwarded-For を使わない）。
 * 負数・小数・文字列は拒否。proxy.ts（必須の環境変数を要求しない）からも使うため単独で公開する。
 */
export function parseTrustedProxyHops(env: Record<string, string | undefined>): number {
  const hopsRaw = env.TRUSTED_PROXY_HOPS?.trim() ?? "";
  if (hopsRaw !== "" && !/^\d+$/.test(hopsRaw)) {
    throw new EnvValidationError(`TRUSTED_PROXY_HOPS は 0 以上の整数にしてください（現在: ${hopsRaw}）`);
  }
  return hopsRaw === "" ? 0 : Number(hopsRaw);
}

function parsePositiveInt(env: Record<string, string | undefined>, key: string, fallback: number): number {
  const raw = env[key]?.trim() ?? "";
  if (raw === "") return fallback;
  if (!/^[1-9]\d{0,8}$/.test(raw)) {
    throw new EnvValidationError(`${key} は 1 以上の整数にしてください（現在: ${raw}）`);
  }
  return Number(raw);
}

/** 回数制限の上限（S1）。未設定・空は既定値。0・負数・小数・文字列は拒否。proxy.ts からも使う */
export function parseRateLimitEnv(env: Record<string, string | undefined>): {
  apiPerMin: number;
  pagePerMin: number;
} {
  return {
    apiPerMin: parsePositiveInt(env, "RATE_LIMIT_API_PER_MIN", DEFAULT_RATE_LIMIT_API_PER_MIN),
    pagePerMin: parsePositiveInt(env, "RATE_LIMIT_PAGE_PER_MIN", DEFAULT_RATE_LIMIT_PAGE_PER_MIN),
  };
}

/**
 * 環境変数を検証して型付きの設定を返す。問題があれば EnvValidationError を投げる。
 * - `NEXT_PUBLIC_*` に秘密の名前があれば拒否（UT-WEB-05）
 * - 必須キーの欠落・空文字を拒否
 * - APP_ENV は development | test | production のみ（未設定は development）
 * - TRUSTED_PROXY_HOPS は任意。0 以上の整数のみ（未設定・空は 0）
 * - RATE_LIMIT_API_PER_MIN・RATE_LIMIT_PAGE_PER_MIN は任意。1 以上の整数のみ（未設定・空は 120・600）
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

  const trustedProxyHops = parseTrustedProxyHops(env);
  const rateLimit = parseRateLimitEnv(env);

  return {
    API_BASE_URL: (env.API_BASE_URL ?? "").trim().replace(/\/+$/, ""),
    INTERNAL_TOKEN: (env.INTERNAL_TOKEN ?? "").trim(),
    IMAGE_BASE_URL: (env.IMAGE_BASE_URL ?? "").trim().replace(/\/+$/, ""),
    SESSION_COOKIE_DOMAIN: env.SESSION_COOKIE_DOMAIN?.trim() ?? "",
    APP_ENV: appEnvRaw as AppEnv,
    TRUSTED_PROXY_HOPS: trustedProxyHops,
    RATE_LIMIT_API_PER_MIN: rateLimit.apiPerMin,
    RATE_LIMIT_PAGE_PER_MIN: rateLimit.pagePerMin,
  };
}
