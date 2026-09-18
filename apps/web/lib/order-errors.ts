import type { ApiErrorBody } from "@/lib/types";

/**
 * 注文系 API（`/api/checkout/prepare`・`/api/orders`）のエラー応答 → 画面の戻し先（純粋関数）。
 * 設計仕様書 3.2・6.8・4.5 と Wave 2 の API 申し送り（クロミ）の対応表をそのまま写している。
 *
 * | 応答 | 戻し先 |
 * | 400 validation_error | SCR-005 の該当項目に赤字（fields を対応付け） |
 * | 404 not_found | カート画面へ（Cookie が無効） |
 * | 409 out_of_stock {items} | カート画面へ。該当明細を強調 |
 * | 409 price_changed {amounts} | SCR-005 へ戻す。確認画面を再表示するときに prepare を呼び直す |
 * | 409 payment_failed {order_number} | SCR-005 の支払い方法へ。prepare を呼び直して新しいキーで再注文 |
 * | 409 already_ordered {order_number} | 完了画面に既存の番号を表示（2 タブ） |
 * | 409 empty_cart | カート画面へ |
 * | 422 unsupported_value | 通常発生しない。汎用トースト |
 * | 403 forbidden（BFF の CSRF） | トースト「ページを再読み込みしてください」 |
 * | 503 upstream_unavailable ／ 5xx | その場に留まりトースト |
 */

export type OrderErrorRoute =
  /** SCR-005 に戻り、項目ごとの赤字を出す */
  | { kind: "field_errors"; fields: unknown; message: string }
  /** カート画面へ。`variantIds` があれば該当明細を強調する */
  | { kind: "cart"; message: string; variantIds: number[] }
  /** SCR-005 へ戻す。`refetchPrepare` は確認画面を開き直すときに prepare を呼び直す印 */
  | { kind: "checkout"; message: string; focus: "form" | "payment"; refetchPrepare: true }
  /** 完了画面へ（既存の注文番号） */
  | { kind: "complete"; orderNumber: string; message: string }
  /** その場に留まってトーストだけ出す */
  | { kind: "stay"; message: string };

export const ORDER_MESSAGES = {
  validation: "入力内容に誤りがあります。赤字の項目を確認してください",
  cartInvalid: "カートの情報が無効になりました。もう一度カートからお進みください",
  outOfStock: "在庫切れの商品があります",
  priceChanged: "金額が変わりました。内容をご確認のうえ、もう一度お進みください",
  paymentFailed: "決済に失敗しました。支払い方法をご確認ください",
  alreadyOrdered: "このカートはすでに注文済みです",
  emptyCart: "カートに商品が入っていません",
  forbidden: "ページを再読み込みしてからもう一度お試しください",
  unavailable: "サーバーに接続できません。時間をおいてお試しください",
  generic: "処理に失敗しました。時間をおいてお試しください",
  rateLimited: "しばらくしてからお試しください",
} as const;

function toVariantIds(items: unknown): number[] {
  if (!Array.isArray(items)) return [];
  const ids: number[] = [];
  for (const it of items) {
    if (typeof it === "number" && Number.isInteger(it)) ids.push(it);
    else if (typeof it === "object" && it !== null && Number.isInteger((it as { variant_id?: unknown }).variant_id)) {
      ids.push((it as { variant_id: number }).variant_id);
    }
  }
  return ids;
}

export function routeOrderError(status: number, body: ApiErrorBody | null): OrderErrorRoute {
  const code = body?.code;
  const orderNumber = typeof body?.order_number === "string" ? body.order_number : null;

  if (status === 400 && code === "validation_error") {
    return { kind: "field_errors", fields: body?.fields ?? [], message: ORDER_MESSAGES.validation };
  }
  if (status === 403) return { kind: "stay", message: ORDER_MESSAGES.forbidden };
  if (status === 404) return { kind: "cart", message: ORDER_MESSAGES.cartInvalid, variantIds: [] };
  if (status === 409) {
    switch (code) {
      case "out_of_stock":
        return { kind: "cart", message: ORDER_MESSAGES.outOfStock, variantIds: toVariantIds(body?.items) };
      case "price_changed":
        return { kind: "checkout", message: ORDER_MESSAGES.priceChanged, focus: "form", refetchPrepare: true };
      case "payment_failed":
        return { kind: "checkout", message: ORDER_MESSAGES.paymentFailed, focus: "payment", refetchPrepare: true };
      case "already_ordered":
        if (orderNumber) return { kind: "complete", orderNumber, message: ORDER_MESSAGES.alreadyOrdered };
        return { kind: "cart", message: ORDER_MESSAGES.alreadyOrdered, variantIds: [] };
      case "empty_cart":
        return { kind: "cart", message: ORDER_MESSAGES.emptyCart, variantIds: [] };
      default:
        return { kind: "stay", message: ORDER_MESSAGES.generic };
    }
  }
  if (status === 429) return { kind: "stay", message: ORDER_MESSAGES.rateLimited };
  if (status === 503 || code === "upstream_unavailable") return { kind: "stay", message: ORDER_MESSAGES.unavailable };
  return { kind: "stay", message: ORDER_MESSAGES.generic };
}

/** 注文照会（`POST /api/orders/[n]/lookup`）の失敗文言。404 は番号・メールを区別せず一括表示（ST-F025-02） */
export function lookupErrorMessage(status: number, body: ApiErrorBody | null): string {
  if (status === 404) return "注文番号かメールアドレスが違います";
  if (status === 429) return ORDER_MESSAGES.rateLimited;
  if (status === 400) return "メールアドレスの形式が正しくありません";
  if (status === 403) return ORDER_MESSAGES.forbidden;
  if (status === 503 || body?.code === "upstream_unavailable") return ORDER_MESSAGES.unavailable;
  return ORDER_MESSAGES.generic;
}

/** 注文番号の形式 `GU-YYMMDD-XXXXXXXX`（設計 DS-PRC-014-1 手順 8。I/O/0/1 を含まない 8 文字） */
export const ORDER_NUMBER_RE = /^GU-[0-9]{6}-[A-HJ-NP-Z2-9]{8}$/;

export function isOrderNumber(s: unknown): s is string {
  return typeof s === "string" && ORDER_NUMBER_RE.test(s);
}
