import { pickAdminBody, proxyAdminRequest } from "@/lib/server/admin-proxy";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 注文状態の更新 BFF（DS-API-053b 取り次ぎ。設計仕様書 P2 追補c 4.4・4.5・DS-DEC-117、テスト IT-BFF-051・053〜055）。
 * - 白リスト：status（必須）・tracking_number。`receive_method`・`total`・`member_id` などは落とす
 * - 更新先の判定（preparing・shipped・delivered のみ）と遷移表は FastAPI が行う。注文番号の形が違えば FastAPI が 404 にする
 *   （パスは URL エンコードして渡す）
 */

export const dynamic = "force-dynamic";

// Next.js 16 では `params` が Promise なので必ず await する
type Ctx = { params: Promise<{ orderNumber: string }> };

export async function PATCH(request: Request, ctx: Ctx) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const { orderNumber } = await ctx.params;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const { payload, fields } = pickAdminBody(parsed.body, {
    fields: { status: "string", tracking_number: "string" },
    required: ["status"],
  });
  if (fields.length > 0) return validationError(request, fields);

  return proxyAdminRequest(request, `/admin/orders/${encodeURIComponent(orderNumber)}/status`, {
    mode: "update",
    method: "PATCH",
    json: payload,
  });
}
