/**
 * BFF の入力範囲チェック（セキュリティ強化 S7）。純粋関数なので `server-only` を付けず Vitest から直接テストする。
 * 業務上の上限（1 明細 10・合計 50）は FastAPI の判定（422 limit_exceeded）。ここは「桁あふれ・異常値」を弾くだけの門番。
 */

/** `quantity` の BFF 上の範囲。11〜99 は FastAPI に渡して 422 limit_exceeded になる */
export const BFF_QUANTITY_MIN = 1;
export const BFF_QUANTITY_MAX = 99;
/** `variant_id`・`item_id` の範囲 1〜2^53-1（JavaScript で正確に扱える整数の上限） */
export const BFF_ID_MIN = 1;
export const BFF_ID_MAX = Number.MAX_SAFE_INTEGER;

/** 1〜99 の整数か（小数・文字列・NaN・Infinity は不可） */
export function isValidQuantity(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= BFF_QUANTITY_MIN && value <= BFF_QUANTITY_MAX;
}

/** 1〜2^53-1 の整数か */
export function isValidId(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= BFF_ID_MIN && value <= BFF_ID_MAX;
}
