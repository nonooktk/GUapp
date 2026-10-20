import { pickAdminBody, pathParamError, POSITIVE_ID_PATH_SHAPE, proxyAdminRequest } from "@/lib/server/admin-proxy";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 在庫の更新 BFF（DS-API-051c 取り次ぎ。設計仕様書 P2 追補c 4.2・4.5・DS-DEC-114・115、テスト IT-BFF-051・053〜055）。
 * - 白リスト：stock・expected_stock（どちらも整数で必須。`sku`・`variant_id` などは落とす）。型が違えば 400（FastAPI を呼ばない）
 * - 在庫の範囲（0〜9999）と再入荷通知の起動は FastAPI が行う
 */

export const dynamic = "force-dynamic";

// Next.js 16 では `params` が Promise なので必ず await する
type Ctx = { params: Promise<{ variantId: string }> };

export async function PATCH(request: Request, ctx: Ctx) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const { variantId } = await ctx.params;
  const badPath = pathParamError(request, "variant_id", variantId, POSITIVE_ID_PATH_SHAPE);
  if (badPath) return badPath;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const { payload, fields } = pickAdminBody(parsed.body, {
    fields: { stock: "int", expected_stock: "int" },
    required: ["stock", "expected_stock"],
  });
  if (fields.length > 0) return validationError(request, fields);

  return proxyAdminRequest(request, `/admin/variants/${variantId}/stock`, { mode: "update", method: "PATCH", json: payload });
}
