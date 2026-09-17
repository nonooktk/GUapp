/**
 * 金額表示（テスト設計書 UT-WEB-04）。
 * 通貨記号は必ず半角 `¥`（U+00A5）。`Intl.NumberFormat` の通貨書式は実行環境によって全角 `￥`（U+FFE5）に
 * なることがあるため使わず、記号は文字列で固定し 3 桁区切りだけ `toLocaleString` に任せる。
 */

export const YEN_SIGN = "¥";

export function formatYen(amount: number): string {
  if (!Number.isFinite(amount)) return `${YEN_SIGN}0`;
  const rounded = Math.trunc(amount);
  const sign = rounded < 0 ? "-" : "";
  return `${sign}${YEN_SIGN}${Math.abs(rounded).toLocaleString("ja-JP")}`;
}

/** 「4,990 円以上で無料」のように円記号なしの 3 桁区切りが欲しいとき */
export function formatNumber(amount: number): string {
  return Math.trunc(amount).toLocaleString("ja-JP");
}
