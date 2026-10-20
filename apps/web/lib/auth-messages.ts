import type { ApiErrorBody } from "@/lib/types";

/**
 * 認証系 BFF（`/api/auth/*`）のエラー応答 → 画面の文言（純粋関数。設計仕様書 6.3・テスト UT-WEB-25）。
 * - 内部のコード（`invalid_credentials` など）は画面に出さない。未知のコードは汎用文言にする
 * - ログインの 401 は「どちらが違うか」を書かない（ユーザー列挙の防止。DS-DEC-71）。403 は残り時間・回数を書かない
 */

export const AUTH_MESSAGES = {
  invalidCredentials: "メールアドレスまたはパスワードが違います",
  accountLocked: "ログインを一時的に止めています。しばらくしてからもう一度お試しください",
  rateLimited: "試行が多すぎます。しばらくしてからお試しください",
  unavailable: "接続できません",
  weakPassword: "よくあるパスワードやメールアドレスと同じ値は使えません",
  unsupportedEmail: "このサイトでは使えないメールアドレスです",
  invalidLink: "リンクが無効か、期限が切れています",
  validation: "入力内容を確認してください",
  forbidden: "ページを再読み込みしてからもう一度お試しください",
  generic: "処理に失敗しました。時間をおいてお試しください",
} as const;

export function authErrorMessage(status: number, body: ApiErrorBody | null): string {
  const code = body?.code;
  if (status === 401 && code === "invalid_credentials") return AUTH_MESSAGES.invalidCredentials;
  if (status === 403 && code === "account_locked") return AUTH_MESSAGES.accountLocked;
  if (status === 403) return AUTH_MESSAGES.forbidden;
  if (status === 429) return AUTH_MESSAGES.rateLimited;
  if (status === 503 || code === "upstream_unavailable") return AUTH_MESSAGES.unavailable;
  if (status === 422 && code === "weak_password") return AUTH_MESSAGES.weakPassword;
  if (status === 422 && code === "unsupported_value") return AUTH_MESSAGES.unsupportedEmail;
  if (status === 404) return AUTH_MESSAGES.invalidLink;
  if (status === 400 && code === "validation_error") return AUTH_MESSAGES.validation;
  return AUTH_MESSAGES.generic;
}

export type RegisterField = "email" | "password" | "name" | "birth_date" | "gender";
export type RegisterErrors = Partial<Record<RegisterField | "form", string>>;

const REGISTER_FIELD_MESSAGES: Record<RegisterField, string> = {
  email: "メールアドレスの形式を確認してください",
  password: "パスワードは 8〜128 文字で入力してください",
  name: "氏名は 1〜50 文字で入力してください",
  birth_date: "生年月日を確認してください",
  gender: "性別を確認してください",
};

/**
 * 登録の 400 `validation_error` の `fields` を項目ごとのエラーに対応付ける。
 * 未知の項目名は捨てる（内部名を画面に出さない）。`reason` は使わず項目ごとの固定文にする。
 */
export function mapRegisterFieldErrors(fields: unknown): RegisterErrors {
  const errors: RegisterErrors = {};
  if (!Array.isArray(fields)) return errors;
  for (const f of fields) {
    if (typeof f !== "object" || f === null) continue;
    const name = (f as { name?: unknown }).name;
    if (typeof name === "string" && name in REGISTER_FIELD_MESSAGES) {
      errors[name as RegisterField] = REGISTER_FIELD_MESSAGES[name as RegisterField];
    }
  }
  return errors;
}

/** 登録・再設定の要求・ログインの 3 ページに常時表示する注意書き（DS-DEC-47 の延長。設計仕様書 6.3） */
export const AUTH_DEMO_NOTICE = "講義演習用のデモです。実在のメールアドレス・氏名は入力せず、demo@example.com のようなダミーの値を使ってください。";
