import { pickBody, proxyAuthRequest } from "@/lib/server/auth-proxy";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";
import { isValidId } from "@/lib/request-validation";

/**
 * 再入荷通知の申込 BFF（DS-API-007 取り次ぎ。設計仕様書 4.5・DS-DEC-80、テスト IT-BFF-007）。
 * - CSRF 検証に失敗したら 403 で FastAPI へ到達させない。本文は 8KB まで（413）
 * - 本文は variant_id（1〜2^53-1 の整数）と email だけ。`member_id`・`notified_at` などは落とす
 * - 有効な形の Cookie `sid` があれば `X-Session-Token` を付ける（FastAPI が member_id を記録する。無効ならゲストの申込）
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const { payload, fields } = pickBody(parsed.body, { required: ["email"] });
  const variantId = parsed.body.variant_id;
  if (!isValidId(variantId)) fields.push({ name: "variant_id", reason: typeof variantId === "number" ? "out_of_range" : "required" });
  else payload.variant_id = variantId;
  if (fields.length > 0) return validationError(request, fields);

  return proxyAuthRequest(request, "/restock-notifications", { json: payload, forwardSession: true });
}
