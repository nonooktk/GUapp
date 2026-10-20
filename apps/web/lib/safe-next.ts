/**
 * ログイン後の遷移先 `next` の検査（設計仕様書 6.3・DS-DEC-85・テスト UT-WEB-14、オープンリダイレクト対策 C-04）。
 *
 * `next` に使えるのはサイト内の既定の遷移先だけ。URL の解釈の差（`//`・`\`・`%2F`）に依存しないよう、
 * 先頭の `/` で始まるパス部分（クエリ・フラグメントは捨てる）を取り出して、次の許可リストに**完全一致**するときだけ返す。
 *   `/mypage`・`/checkout`・`/cart`・`/products/<数字のみ>`
 * それ以外（`//evil.example`・`/\evil.example`・`https://…`・`javascript:…`・`%2F%2F` を含む値・未指定・極端に長い値）は `/mypage`。
 * 純粋関数なので `server-only` を付けず、Server Component／Client Component／Vitest のどこからでも使える。
 */

export const DEFAULT_NEXT = "/mypage";
/** これより長い値は読まずに既定へ（巨大な値の正規表現評価を避ける） */
const MAX_RAW_LENGTH = 512;

const ALLOWED = /^(?:\/mypage|\/checkout|\/cart|\/products\/[0-9]{1,18})$/;

export function safeNext(raw: unknown): string {
  if (typeof raw !== "string" || raw.length === 0 || raw.length > MAX_RAW_LENGTH) return DEFAULT_NEXT;
  // 先頭が単一の `/` でなければ（`//`・`/\`・スキーム付き・相対）拒否
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return DEFAULT_NEXT;
  const path = raw.split(/[?#]/, 1)[0];
  return ALLOWED.test(path) ? path : DEFAULT_NEXT;
}

/** searchParams の値（string | string[] | undefined）から先頭の 1 つを取り出す */
export function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** `?page=` を 1 以上の整数に直す（最大 6 桁）。不正な値は 1 */
export function parsePage(raw: string | undefined): number {
  return raw !== undefined && /^[1-9][0-9]{0,5}$/.test(raw) ? Number(raw) : 1;
}
