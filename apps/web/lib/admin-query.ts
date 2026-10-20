import { ADMIN_ORDER_STATUS_OPTIONS } from "@/lib/admin-types";
import { firstParam, parsePage } from "@/lib/safe-next";

/**
 * 管理画面の一覧の検索条件（URL のクエリ）を読む純粋関数（設計仕様書 P2 追補c 6.4・6.5、テスト UT-WEB-43・46）。
 * Server Component が `searchParams` をこれに通し、**検査を通した値だけ**を FastAPI のクエリに載せる。
 * - 列挙外は既定に戻す。配列（`?q=a&q=b`）は先頭の 1 つ。`page` は 1 以上の整数（6 桁まで）以外なら 1
 * - 検索語は NFKC 正規化・前後空白除去のあと 50 文字までに切る
 * - 注文の日付・注文番号・メールは形が違えば FastAPI に渡さず、画面にエラーを出す（`errors`）
 */

type SearchParamValue = string | string[] | undefined;
export type SearchParamsRecord = Record<string, SearchParamValue>;

export const PRODUCT_Q_MAX_LENGTH = 50;
const ORDER_NUMBER_SHAPE = /^GU-[0-9]{6}-[A-HJ-NP-Z2-9]{8}$/;
const DATE_SHAPE = /^(\d{4})-(\d{2})-(\d{2})$/;
/** メールの上限（254 文字）。形は「空白なしの `@` を 1 つ含む」程度の門番で、厳密な検査は FastAPI */
const EMAIL_MAX_LENGTH = 254;
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+$/;
/** 画面に echo する生の値の上限（巨大な値を input の value に戻さない） */
const ECHO_MAX = 300;

function str(value: SearchParamValue): string {
  const v = firstParam(value);
  return typeof v === "string" ? v : "";
}

function nfkcTrim(value: string): string {
  return value.normalize("NFKC").trim();
}

function cutChars(value: string, max: number): string {
  const chars = Array.from(value);
  return chars.length > max ? chars.slice(0, max).join("") : value;
}

// ---- 商品 ----

export type ProductVisibility = "all" | "public" | "private";
export type ProductStockFilter = "all" | "out";

export interface ProductQuery {
  q: string;
  visibility: ProductVisibility;
  stock: ProductStockFilter;
  page: number;
  /** FastAPI へ渡すクエリ文字列（検査済みの値だけ。`?` なし） */
  apiQuery: string;
  /** ページ送りのリンクに保つ検索条件（既定値は省く。`page` は含めない） */
  linkParams: Record<string, string>;
}

export function parseProductQuery(sp: SearchParamsRecord): ProductQuery {
  const q = cutChars(nfkcTrim(str(sp.q)), PRODUCT_Q_MAX_LENGTH);
  const v = str(sp.visibility);
  const visibility: ProductVisibility = v === "public" || v === "private" ? v : "all";
  const stock: ProductStockFilter = str(sp.stock) === "out" ? "out" : "all";
  const page = parsePage(firstParam(sp.page));

  const linkParams: Record<string, string> = {};
  if (q) linkParams.q = q;
  if (visibility !== "all") linkParams.visibility = visibility;
  if (stock !== "all") linkParams.stock = stock;

  const api = new URLSearchParams(linkParams);
  api.set("page", String(page));
  return { q, visibility, stock, page, apiQuery: api.toString(), linkParams };
}

// ---- 注文 ----

export type OrderQueryErrorField = "from" | "to" | "order_number" | "email";

export interface OrderQuery {
  /** フォームに戻す値（形が違う入力も、直せるようにそのまま戻す） */
  values: { status: string; receive_method: string; from: string; to: string; order_number: string; email: string };
  page: number;
  errors: Partial<Record<OrderQueryErrorField, string>>;
  /** FastAPI へ渡すクエリ文字列。1 つでも形が違えば null（呼ばない） */
  apiQuery: string | null;
  linkParams: Record<string, string>;
}

const STATUS_VALUES: readonly string[] = ADMIN_ORDER_STATUS_OPTIONS.map((o) => o.value);

/** `YYYY-MM-DD` が実在する日付か（2026-02-30 は不可）。実在すれば UTC 0 時の ms を返す */
export function parseIsoDate(value: string): number | null {
  const m = DATE_SHAPE.exec(value);
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const ms = Date.UTC(y, mo - 1, d);
  const back = new Date(ms);
  return back.getUTCFullYear() === y && back.getUTCMonth() === mo - 1 && back.getUTCDate() === d ? ms : null;
}

export const ORDER_QUERY_MESSAGES = {
  date: "日付は YYYY-MM-DD の形で、実在する日付を入力してください",
  order: "注文番号の形式が正しくありません（例：GU-261024-ABCDEFGH）",
  email: "メールアドレスの形式が正しくありません",
  reversed: "期間の開始日は終了日以前にしてください",
} as const;

export function parseOrderQuery(sp: SearchParamsRecord): OrderQuery {
  const statusRaw = str(sp.status);
  const status = STATUS_VALUES.includes(statusRaw) ? statusRaw : "all";
  const rm = str(sp.receive_method);
  const receive_method = rm === "delivery" || rm === "store" ? rm : "all";
  const page = parsePage(firstParam(sp.page));

  const errors: OrderQuery["errors"] = {};
  const rawFrom = cutChars(nfkcTrim(str(sp.from)), ECHO_MAX);
  const rawTo = cutChars(nfkcTrim(str(sp.to)), ECHO_MAX);
  const rawOrder = cutChars(nfkcTrim(str(sp.order_number)), ECHO_MAX);
  const rawEmail = cutChars(nfkcTrim(str(sp.email)), ECHO_MAX);

  let fromMs: number | null = null;
  let toMs: number | null = null;
  if (rawFrom) {
    fromMs = parseIsoDate(rawFrom);
    if (fromMs === null) errors.from = ORDER_QUERY_MESSAGES.date;
  }
  if (rawTo) {
    toMs = parseIsoDate(rawTo);
    if (toMs === null) errors.to = ORDER_QUERY_MESSAGES.date;
  }
  if (fromMs !== null && toMs !== null && fromMs > toMs) errors.to = ORDER_QUERY_MESSAGES.reversed;

  const orderNumber = rawOrder.toUpperCase();
  if (rawOrder && !ORDER_NUMBER_SHAPE.test(orderNumber)) errors.order_number = ORDER_QUERY_MESSAGES.order;

  const email = rawEmail.toLowerCase();
  if (rawEmail && (email.length > EMAIL_MAX_LENGTH || !EMAIL_SHAPE.test(email))) errors.email = ORDER_QUERY_MESSAGES.email;

  const hasErrors = Object.keys(errors).length > 0;

  // 検査を通した値だけを FastAPI とリンクに載せる
  const linkParams: Record<string, string> = {};
  if (status !== "all") linkParams.status = status;
  if (receive_method !== "all") linkParams.receive_method = receive_method;
  if (rawFrom && !errors.from) linkParams.from = rawFrom;
  if (rawTo && !errors.to) linkParams.to = rawTo;
  if (rawOrder && !errors.order_number) linkParams.order_number = orderNumber;
  if (rawEmail && !errors.email) linkParams.email = email;

  let apiQuery: string | null = null;
  if (!hasErrors) {
    const api = new URLSearchParams(linkParams);
    api.set("page", String(page));
    apiQuery = api.toString();
  }

  return {
    values: { status, receive_method, from: rawFrom, to: rawTo, order_number: rawOrder, email: rawEmail },
    page,
    errors,
    apiQuery,
    linkParams,
  };
}

/** 一覧ページのリンク（検索条件を保ち、`page` だけを差し替える）。`page` は 1 以上の整数に直す */
export function buildListHref(basePath: string, linkParams: Record<string, string>, page: number): string {
  const p = new URLSearchParams(linkParams);
  const safePage = Number.isInteger(page) && page >= 1 ? page : 1;
  if (safePage > 1) p.set("page", String(safePage));
  const qs = p.toString();
  return qs ? `${basePath}?${qs}` : basePath;
}
