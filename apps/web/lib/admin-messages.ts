import type { ApiErrorBody } from "@/lib/types";

/**
 * 管理画面のエラー応答 → 画面の文言（純粋関数。設計仕様書 P2 追補c 6.7・テスト UT-WEB-49）。
 * - 内部のコード（`invalid_credentials` など）は画面に出さない。未知のコードは汎用文言にする
 * - ログインの 401 は「ID とパスワードのどちらが違うか」を書かない。403 `account_locked` は残り時間・回数を書かない
 * - `stale_data` の文言には `current`（他の操作で変わった後の現在の値）を入れる
 */

export const ADMIN_MESSAGES = {
  invalidCredentials: "ログイン ID またはパスワードが違います",
  accountLocked: "ログインを一時的に止めています。しばらくしてからもう一度お試しください",
  rateLimited: "試行回数が多すぎます。しばらくしてからもう一度お試しください",
  sessionExpired: "セッションの有効期限が切れました。もう一度ログインしてください",
  forbidden: "画面を読み込み直してから、もう一度お試しください",
  unavailable: "サーバーに接続できません。しばらくしてからもう一度お試しください",
  invalidTransition: "この注文の状態はすでに変わっています。画面を更新しました",
  trackingNotAllowed: "追跡番号を付けられない注文です",
  generic: "処理に失敗しました",
  saved: "保存しました",
  noChange: "変更はありませんでした",
  loginExpiredNotice: "セッションの有効期限が切れました。もう一度ログインしてください",
} as const;

/** 項目名（API のフィールド名 → 画面の呼び名） */
const FIELD_LABELS: Record<string, string> = {
  price_incl_tax: "価格",
  published: "公開状態",
  stock: "在庫",
  tax_rate: "消費税率",
  shipping_fee: "送料",
  free_shipping_threshold: "送料無料の下限",
  tracking_number: "追跡番号",
  status: "状態",
  login_id: "ログイン ID",
  password: "パスワード", // pragma: allowlist secret（項目の表示名。秘密ではない）
};

/** 業務の範囲（設計仕様書 4 章）。422 の文言「{項目名}は {下限} 以上 {上限} 以下で入力してください」に使う */
export const ADMIN_FIELD_RANGES: Record<string, { min: string; max: string }> = {
  price_incl_tax: { min: "1", max: "1,000,000" },
  stock: { min: "0", max: "9,999" },
  tax_rate: { min: "0.00", max: "0.30" },
  shipping_fee: { min: "0", max: "5,000" },
  free_shipping_threshold: { min: "0", max: "100,000" },
};

export function adminFieldLabel(name: string | undefined): string | null {
  return name !== undefined && Object.hasOwn(FIELD_LABELS, name) ? FIELD_LABELS[name] : null;
}

/** 範囲外の文言（クライアントでの事前検査と 422 の両方で使う）。範囲が未定義の項目は null */
export function adminRangeMessage(field: string | undefined): string | null {
  if (field === undefined || !Object.hasOwn(ADMIN_FIELD_RANGES, field)) return null;
  const range = ADMIN_FIELD_RANGES[field];
  const label = adminFieldLabel(field) ?? field;
  return `${label}は ${range.min} 以上 ${range.max} 以下で入力してください`;
}

/** 形式不正の文言 */
export function adminFormatMessage(field: string | undefined): string {
  const label = adminFieldLabel(field);
  return label ? `${label}の形式が正しくありません` : "入力内容の形式が正しくありません";
}

/** `stale_data` の `current` を画面に出す文字列にする。公開状態は「公開／非公開」、数値・文字列はそのまま */
export function formatCurrent(current: unknown, field?: string): string {
  if (typeof current === "boolean") return current ? "公開" : "非公開";
  if (typeof current === "number" && Number.isFinite(current)) {
    return field === "price_incl_tax" ? current.toLocaleString("ja-JP") : String(current);
  }
  if (typeof current === "string") return current.slice(0, 40);
  return "不明";
}

/** 失敗した項目名（400 の `fields[0].name`、422・409 の `field`） */
function failedField(body: ApiErrorBody | null): string | undefined {
  if (!body) return undefined;
  if (typeof body.field === "string") return body.field;
  const fields = (body as { fields?: unknown }).fields;
  if (Array.isArray(fields)) {
    const first = fields[0] as { name?: unknown } | undefined;
    if (first && typeof first.name === "string") return first.name;
  }
  return undefined;
}

/** 401 `unauthorized`（変更系の操作中にセッションが切れた）か。画面は `/admin/login?expired=1` へ移す */
export function isSessionExpired(status: number, body: ApiErrorBody | null): boolean {
  return status === 401 && body?.code === "unauthorized";
}

export function adminErrorMessage(status: number, body: ApiErrorBody | null): string {
  const code = body?.code;
  if (code === "invalid_credentials") return ADMIN_MESSAGES.invalidCredentials;
  if (code === "account_locked") return ADMIN_MESSAGES.accountLocked;
  if (status === 429 || code === "rate_limited") return ADMIN_MESSAGES.rateLimited;
  if (status === 401) return ADMIN_MESSAGES.sessionExpired;
  if (status === 403) return ADMIN_MESSAGES.forbidden;
  if (code === "stale_data") {
    const field = failedField(body);
    return `他の操作で値が変わっていました（現在の値：${formatCurrent(body?.current, field)}）。内容を確認してもう一度保存してください`;
  }
  if (code === "invalid_transition") return ADMIN_MESSAGES.invalidTransition;
  if (code === "unsupported_value" || code === "limit_exceeded") {
    const field = failedField(body);
    if (field === "tracking_number") return ADMIN_MESSAGES.trackingNotAllowed;
    return adminRangeMessage(field) ?? ADMIN_MESSAGES.generic;
  }
  if (code === "validation_error") return adminFormatMessage(failedField(body));
  if (status === 503 || status === 500 || status === 502 || code === "upstream_unavailable" || code === "internal_error" || code === "upstream_error") {
    return ADMIN_MESSAGES.unavailable;
  }
  return ADMIN_MESSAGES.generic;
}
