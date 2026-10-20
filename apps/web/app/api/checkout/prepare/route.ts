import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { proxyOrderRequest } from "@/lib/server/order-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 確認画面用の金額計算・冪等キー発行 BFF（DS-API-021 取り次ぎ。設計仕様書 4.3・4.4・DS-PRC-021／021a、テスト IT-BFF-021）。
 * - CSRF 検証に失敗したら 403 で FastAPI へ到達させない。本文は 8KB まで（413）
 * - 本文は任意。あれば `receive_method`（`delivery`／`store`）だけを通す。それ以外の値は 400 で FastAPI を呼ばない。
 *   本文なし（または JSON として読めない）は従来どおり配送として FastAPI に取り次ぐ
 * - 409（empty_cart／out_of_stock／already_ordered）・404 は FastAPI の判定をそのまま返す。
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;

  const payload: Record<string, unknown> = {};
  const method = parsed.body?.receive_method;
  if (method !== undefined && method !== null) {
    if (method !== "delivery" && method !== "store") {
      return validationError(request, [{ name: "receive_method", reason: "format" }]);
    }
    payload.receive_method = method;
  }
  return proxyOrderRequest(request, "/checkout/prepare", { json: payload });
}
