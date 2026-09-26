/**
 * サイト全体・BFF `/api/*` を保護する HTTP Basic 認証（公開追補 設計仕様書 7 章・DS-DEC-49）。
 *
 * 秘密（BASIC_AUTH_USER・BASIC_AUTH_PASSWORD）そのものは扱うが、値を直接 process.env から
 * 読むのはこのファイルの呼び出し側（proxy.ts）に限定する。ここは純粋関数のみを置き、
 * Vitest から直接テストできるようにする（`server-only` は付けない。設計仕様書 7.2 の対象は
 * クライアントに秘密が漏れる経路であり、この関数自体はどこから呼んでも安全なため）。
 *
 * Next.js 16 は proxy（旧 middleware）の既定ランタイムが Node.js になったため（バージョン調査済み）、
 * `node:crypto` をそのまま import してよい。
 */

import { createHash, timingSafeEqual } from "node:crypto";

export class BasicAuthConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BasicAuthConfigError";
  }
}

export interface BasicAuthConfig {
  user: string;
  password: string;
}

/**
 * 環境変数から Basic 認証の設定を組み立てる。
 * - 両方未設定（または空白のみ）: null（認証なし。ローカル開発を妨げない）
 * - 片方だけ設定: BasicAuthConfigError（起動時か初回で失敗させる。設定漏れで無防備にしない）
 * - 両方設定: { user, password }
 */
export function parseBasicAuthConfig(env: Record<string, string | undefined>): BasicAuthConfig | null {
  const user = (env.BASIC_AUTH_USER ?? "").trim();
  const password = (env.BASIC_AUTH_PASSWORD ?? "").trim();

  if (!user && !password) return null;
  if (!user || !password) {
    throw new BasicAuthConfigError(
      "BASIC_AUTH_USER と BASIC_AUTH_PASSWORD は両方設定するか、両方とも未設定にしてください（片方だけの設定は不可）。",
    );
  }
  return { user, password };
}

/** 文字列を固定長のダイジェストにしてから比較する（長さの違いで早期リターンしない時間一定比較）。*/
function timingSafeEqualString(a: string, b: string): boolean {
  const digestA = createHash("sha256").update(a, "utf-8").digest();
  const digestB = createHash("sha256").update(b, "utf-8").digest();
  return timingSafeEqual(digestA, digestB);
}

/**
 * `Authorization` ヘッダの値を検証する。例外は投げず、常に true/false を返す
 * （不正な base64・書式違反も「認証失敗」として扱う）。
 */
export function verifyBasicAuthHeader(
  header: string | null | undefined,
  expectedUser: string,
  expectedPassword: string,
): boolean {
  if (!header) return false;

  const match = /^Basic\s+(.+)$/i.exec(header.trim());
  if (!match) return false;

  let decoded: string;
  try {
    decoded = Buffer.from(match[1], "base64").toString("utf-8");
  } catch {
    return false;
  }

  const separatorIndex = decoded.indexOf(":");
  if (separatorIndex < 0) return false;

  const user = decoded.slice(0, separatorIndex);
  const password = decoded.slice(separatorIndex + 1);

  const userOk = timingSafeEqualString(user, expectedUser);
  const passwordOk = timingSafeEqualString(password, expectedPassword);
  return userOk && passwordOk;
}
