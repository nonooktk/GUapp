import { pickAdminBody, pathParamError, POSITIVE_ID_PATH_SHAPE, proxyAdminRequest } from "@/lib/server/admin-proxy";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 商品の更新 BFF（DS-API-051b 取り次ぎ。設計仕様書 P2 追補c 4.2・4.5・DS-DEC-113・116、テスト IT-BFF-051・053〜055）。
 * - 白リスト：published・price_incl_tax・expected_published・expected_price_incl_tax。型が違えば 400（FastAPI を呼ばない）
 * - `asid` が無い・形が違うときは FastAPI を呼ばずに 401。値の範囲（価格 1〜1,000,000）と `expected_*` の対応は FastAPI が判定する
 */

export const dynamic = "force-dynamic";

// Next.js 16 では `params` が Promise なので必ず await する
type Ctx = { params: Promise<{ productId: string }> };

export async function PATCH(request: Request, ctx: Ctx) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const { productId } = await ctx.params;
  const badPath = pathParamError(request, "product_id", productId, POSITIVE_ID_PATH_SHAPE);
  if (badPath) return badPath;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const { payload, fields } = pickAdminBody(parsed.body, {
    fields: { published: "boolean", price_incl_tax: "int", expected_published: "boolean", expected_price_incl_tax: "int" },
  });
  if (fields.length > 0) return validationError(request, fields);

  return proxyAdminRequest(request, `/admin/products/${productId}`, { mode: "update", method: "PATCH", json: payload });
}
