import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { proxyOrderRequest } from "@/lib/server/order-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 注文確定 BFF（DS-API-022 取り次ぎ。設計仕様書 4.3・4.4・DS-PRC-014-1／014-3、テスト IT-BFF-01/02・IT-BFF-022）。
 * - CSRF 検証（Double Submit Cookie）に失敗したら 403 `{code:"forbidden"}` で FastAPI へ到達させない
 * - 本文は 8KB まで（超えたら 413。S2）
 * - 本文は設計 4.4 の項目だけを拾って転送する（余計なキー＝`member_id`・`status`・`pickup_code`・`store_id` などは落とす）。
 *   形の検査（桁・形式）は FastAPI（Pydantic）が 400 にする
 * - P2-b: `receive_method=store` のとき `ship_postal_code`・`ship_address` は必須としない（送られてきても通すが、FastAPI が店舗の値で上書きする）。
 *   `store_code` を通す。有効な形の Cookie `sid` があれば `X-Session-Token` を付ける（FastAPI が注文を会員に紐づける。会員はセッションからだけ決まる）
 * - 201（新規）／200（同じキーの再送）の注文応答をそのまま返す。配送先・メールはログに出さない
 */

export const dynamic = "force-dynamic";

const ALWAYS_STRING_FIELDS = ["idempotency_key", "ship_name", "ship_phone", "guest_email", "receive_method", "payment_method"] as const;
/** 配送では必須、店舗受け取りでは任意（送られてきたら文字列として通す） */
const ADDRESS_FIELDS = ["ship_postal_code", "ship_address"] as const;

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const body = parsed.body;
  if (!body) return validationError(request, [{ name: "body", reason: "format" }]);

  const fields: { name: string; reason: string }[] = [];
  const payload: Record<string, unknown> = {};
  for (const key of ALWAYS_STRING_FIELDS) {
    const v = body[key];
    if (typeof v !== "string") fields.push({ name: key, reason: "required" });
    else payload[key] = v;
  }

  const isStore = body.receive_method === "store";
  for (const key of ADDRESS_FIELDS) {
    const v = body[key];
    if (typeof v === "string") payload[key] = v;
    else if (!isStore) fields.push({ name: key, reason: "required" });
    else if (v !== undefined && v !== null) fields.push({ name: key, reason: "format" });
  }

  const storeCode = body.store_code;
  if (typeof storeCode === "string") payload.store_code = storeCode;
  else if (storeCode !== undefined && storeCode !== null) fields.push({ name: "store_code", reason: "format" });

  const display = body.display;
  if (
    typeof display !== "object" ||
    display === null ||
    !["subtotal", "shipping_fee", "total"].every((k) => Number.isInteger((display as Record<string, unknown>)[k]))
  ) {
    fields.push({ name: "display", reason: "format" });
  } else {
    const d = display as Record<string, number>;
    payload.display = { subtotal: d.subtotal, shipping_fee: d.shipping_fee, total: d.total };
  }
  if (fields.length > 0) return validationError(request, fields);

  return proxyOrderRequest(request, "/orders", { json: payload, session: true });
}
