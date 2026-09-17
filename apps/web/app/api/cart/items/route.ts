import { proxyCartRequest, readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * カート追加 BFF（DS-API-011 取り次ぎ）。本文 `{variant_id, quantity}` → FastAPI `POST /cart/items`（201）。
 * CSRF 検証（Double Submit Cookie）に失敗したら 403 `{code:"forbidden"}` で FastAPI へ到達させない。
 * 業務判定（409 out_of_stock・422 limit_exceeded）は FastAPI 側。ここでは形（整数か）だけ見る。
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const body = await readJsonBody(request);
  const variantId = body?.variant_id;
  const quantity = body?.quantity;
  const fields: { name: string; reason: string }[] = [];
  if (!Number.isInteger(variantId)) fields.push({ name: "variant_id", reason: "format" });
  if (!Number.isInteger(quantity) || (quantity as number) <= 0) fields.push({ name: "quantity", reason: "out_of_range" });
  if (fields.length > 0) return validationError(fields);

  return proxyCartRequest(request, "/cart/items", {
    method: "POST",
    json: { variant_id: variantId, quantity },
  });
}
