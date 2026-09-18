import { isOrderNumber } from "@/lib/order-errors";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { proxyOrderRequest } from "@/lib/server/order-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * ゲスト注文照会 BFF（DS-API-023 取り次ぎ。設計仕様書 4.3、テスト ST-F025-01〜03）。
 * - CSRF 検証 → 注文番号の形式（`GU-YYMMDD-XXXXXXXX`）が違えば FastAPI を呼ばず 404（存在を区別しない）
 * - 本文 `{guest_email}` を転送。番号不存在・メール不一致は FastAPI が 404 にする
 * - 429 のときは `X-Forwarded-For`（接続元 IP）で数えられた結果なので `Retry-After` を透過する
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request, { params }: RouteContext<"/api/orders/[orderNumber]/lookup">) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const { orderNumber } = await params;
  if (!isOrderNumber(orderNumber)) {
    return Response.json({ code: "not_found" }, { status: 404, headers: { "Cache-Control": "no-store" } });
  }

  const body = await readJsonBody(request);
  const email = body?.guest_email;
  if (typeof email !== "string" || email.length === 0 || email.length > 254) {
    return validationError([{ name: "guest_email", reason: "format" }]);
  }

  return proxyOrderRequest(request, `/orders/${encodeURIComponent(orderNumber)}/lookup`, { json: { guest_email: email } });
}
