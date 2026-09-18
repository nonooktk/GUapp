import { proxyOrderRequest } from "@/lib/server/order-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 確認画面用の金額計算・冪等キー発行 BFF（DS-API-021 取り次ぎ。設計仕様書 4.3・DS-PRC-021）。
 * 本文は無し。CSRF 検証に失敗したら 403 で FastAPI へ到達させない。
 * 409（empty_cart／out_of_stock／already_ordered）・404 は FastAPI の判定をそのまま返す。
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;
  return proxyOrderRequest(request, "/checkout/prepare");
}
