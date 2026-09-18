import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { proxyOrderRequest } from "@/lib/server/order-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 注文確定 BFF（DS-API-022 取り次ぎ。設計仕様書 4.3・DS-PRC-014-1、テスト IT-BFF-01/02）。
 * - CSRF 検証（Double Submit Cookie）に失敗したら 403 `{code:"forbidden"}` で FastAPI へ到達させない
 * - 本文は設計 4.4 の項目だけを拾って転送する（余計なキーは落とす）。形の検査（桁・形式）は FastAPI（Pydantic）が 400 にする
 * - 201（新規）／200（同じキーの再送）の注文応答をそのまま返す。配送先・メールはログに出さない
 */

export const dynamic = "force-dynamic";

const STRING_FIELDS = [
  "idempotency_key",
  "ship_name",
  "ship_postal_code",
  "ship_address",
  "ship_phone",
  "guest_email",
  "receive_method",
  "payment_method",
] as const;

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const body = await readJsonBody(request);
  if (!body) return validationError([{ name: "body", reason: "format" }]);

  const fields: { name: string; reason: string }[] = [];
  const payload: Record<string, unknown> = {};
  for (const key of STRING_FIELDS) {
    const v = body[key];
    if (typeof v !== "string") fields.push({ name: key, reason: "required" });
    else payload[key] = v;
  }
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
  if (fields.length > 0) return validationError(fields);

  return proxyOrderRequest(request, "/orders", { json: payload });
}
