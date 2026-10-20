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

/**
 * 受け取りコード（API の値は区切りなしの 8 文字）を 4 文字ずつハイフンで区切る（設計仕様書 6.5・6.8）。
 * 8 文字の英数字でない値はそのまま返す（表示を壊さない）。
 */
export function formatPickupCode(code: string): string {
  return /^[A-Za-z0-9]{8}$/.test(code) ? `${code.slice(0, 4)}-${code.slice(4)}` : code;
}

/**
 * 店舗の住所の表示。API の `address` は都道府県から始まる（seed は「東京都千代田区…」）ので、先頭が都道府県と同じなら重ねない。
 * 都道府県で始まらない住所には都道府県を前に付ける（設計仕様書 4.3 は `prefecture` と `address` を別項目で返す）。
 */
export function formatStoreAddress(store: { prefecture: string; address: string }): string {
  return store.address.startsWith(store.prefecture) ? store.address : `${store.prefecture} ${store.address}`;
}
