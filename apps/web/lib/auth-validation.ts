import { charLength, isValidEmail } from "@/lib/checkout-validation";
import type { RegisterErrors } from "@/lib/auth-messages";

/**
 * 登録・再設定フォームのクライアント検査（純粋関数。設計仕様書 6.3・DS-API-030 と同じ規則。テスト UT-WEB-17・18）。
 * パスワードは NFKC 正規化のあとの文字数で数える（サーバーと同じ。全角・半角の食い違いで長さが変わるため）。
 * サーバーが最終判断をするので、ここは「明らかな誤り」を送る前に止めるだけ。禁止リスト（weak_password）は検査しない。
 */

export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;
export const NAME_MAX = 50;

export const AUTH_FORM_MESSAGES = {
  required: "入力してください",
  email: "メールアドレスの形式を確認してください",
  password: `パスワードは ${PASSWORD_MIN}〜${PASSWORD_MAX} 文字で入力してください`,
  name: `氏名は 1〜${NAME_MAX} 文字で入力してください`,
  confirmMismatch: "確認用のパスワードが一致しません",
} as const;

export function passwordLength(raw: string): number {
  return charLength(raw.normalize("NFKC"));
}

export function isValidPassword(raw: string): boolean {
  const n = passwordLength(raw);
  return n >= PASSWORD_MIN && n <= PASSWORD_MAX;
}

/** メールの前処理（サーバーと同じ: NFKC・前後空白除去）。小文字化はサーバーが行う */
export function normalizeEmailInput(raw: string): string {
  return raw.normalize("NFKC").trim();
}

export interface RegisterFormValues {
  email: string;
  password: string;
  name: string;
  birthDate: string;
  gender: string;
}

export function validateRegisterForm(v: RegisterFormValues): RegisterErrors {
  const errors: RegisterErrors = {};
  const email = normalizeEmailInput(v.email);
  if (email.length === 0) errors.email = AUTH_FORM_MESSAGES.required;
  else if (!isValidEmail(email)) errors.email = AUTH_FORM_MESSAGES.email;

  if (v.password.length === 0) errors.password = AUTH_FORM_MESSAGES.required;
  else if (!isValidPassword(v.password)) errors.password = AUTH_FORM_MESSAGES.password;

  const name = v.name.trim();
  if (name.length === 0) errors.name = AUTH_FORM_MESSAGES.name;
  else if (charLength(name) > NAME_MAX) errors.name = AUTH_FORM_MESSAGES.name;

  if (v.birthDate !== "" && !/^\d{4}-\d{2}-\d{2}$/.test(v.birthDate)) errors.birth_date = "生年月日を確認してください";
  return errors;
}

export interface ResetConfirmValues {
  password: string;
  confirm: string;
}

export interface ResetConfirmErrors {
  password?: string;
  confirm?: string;
}

export function validateResetConfirm(v: ResetConfirmValues): ResetConfirmErrors {
  const errors: ResetConfirmErrors = {};
  if (v.password.length === 0) errors.password = AUTH_FORM_MESSAGES.required;
  else if (!isValidPassword(v.password)) errors.password = AUTH_FORM_MESSAGES.password;
  if (!errors.password && v.password !== v.confirm) errors.confirm = AUTH_FORM_MESSAGES.confirmMismatch;
  return errors;
}

/** 再設定・確認のリンクの token の形（`^[A-Za-z0-9_-]{43}$`。DS-API-031） */
export const EMAIL_TOKEN_SHAPE = /^[A-Za-z0-9_-]{43}$/;

export function isEmailToken(value: unknown): value is string {
  return typeof value === "string" && EMAIL_TOKEN_SHAPE.test(value);
}
