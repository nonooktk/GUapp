import { proxyCartRequest, readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { isValidId, isValidQuantity } from "@/lib/request-validation";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * カート追加 BFF（DS-API-011 取り次ぎ）。本文 `{variant_id, quantity}` → FastAPI `POST /cart/items`（201）。
 * CSRF 検証（Double Submit Cookie）に失敗したら 403 `{code:"forbidden"}` で FastAPI へ到達させない。
 * 業務判定（409 out_of_stock・422 limit_exceeded）は FastAPI 側。ここでは形と範囲だけ見る
 * （quantity は 1〜99 の整数、variant_id は 1〜2^53-1 の整数。11〜99 は FastAPI に渡して 422 limit_exceeded になる。S7）。
 * 本文は 8KB まで（超えたら 413。S2）。
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const variantId = parsed.body?.variant_id;
  const quantity = parsed.body?.quantity;
  const fields: { name: string; reason: string }[] = [];
  if (!Number.isInteger(variantId)) fields.push({ name: "variant_id", reason: "format" });
  else if (!isValidId(variantId)) fields.push({ name: "variant_id", reason: "out_of_range" });
  if (!isValidQuantity(quantity)) fields.push({ name: "quantity", reason: "out_of_range" });
  if (fields.length > 0) return validationError(request, fields);

  return proxyCartRequest(request, "/cart/items", {
    method: "POST",
    json: { variant_id: variantId, quantity },
  });
}
