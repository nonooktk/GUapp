import type { ApiErrorBody } from "@/lib/types";

/**
 * 再入荷のお知らせ申込（`POST /api/restock-notifications`）のエラー応答 → 画面の文言（純粋関数。設計仕様書 6.6・UT-WEB-23）。
 * `kind: "email"` はメール欄の下に出す文言、`kind: "form"` は欄の外（role="alert"）に出す文言。
 */

export const RESTOCK_MESSAGES = {
  done: "申し込みました。入荷したらメールでお知らせします",
  inStock: "在庫が入りました。ページを読み込み直して、カートに入れてください",
  notFound: "この商品は申し込めません",
  limitExceeded: "申し込みの上限（10 件）に達しています",
  unsupportedEmail: "このサイトでは使えないメールアドレスです",
  invalidEmail: "メールアドレスの形式を確認してください",
  rateLimited: "しばらくしてからお試しください",
  forbidden: "ページを再読み込みしてからもう一度お試しください",
  unavailable: "接続できません。時間をおいてお試しください",
  generic: "処理に失敗しました。時間をおいてお試しください",
} as const;

export interface RestockError {
  kind: "email" | "form";
  message: string;
}

export function restockErrorMessage(status: number, body: ApiErrorBody | null): RestockError {
  const code = body?.code;
  if (status === 400) return { kind: "email", message: RESTOCK_MESSAGES.invalidEmail };
  if (status === 404) return { kind: "form", message: RESTOCK_MESSAGES.notFound };
  if (status === 409 && code === "in_stock") return { kind: "form", message: RESTOCK_MESSAGES.inStock };
  if (status === 422 && code === "limit_exceeded") return { kind: "form", message: RESTOCK_MESSAGES.limitExceeded };
  if (status === 422 && code === "unsupported_value") return { kind: "email", message: RESTOCK_MESSAGES.unsupportedEmail };
  if (status === 429) return { kind: "form", message: RESTOCK_MESSAGES.rateLimited };
  if (status === 403) return { kind: "form", message: RESTOCK_MESSAGES.forbidden };
  if (status === 503 || code === "upstream_unavailable") return { kind: "form", message: RESTOCK_MESSAGES.unavailable };
  return { kind: "form", message: RESTOCK_MESSAGES.generic };
}
