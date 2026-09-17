import { proxyCartRequest, readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * カート明細の数量変更・削除 BFF（DS-API-012/013 取り次ぎ）。
 * `[id]` は FastAPI の `item_id`（設計仕様書 7.5 の例外として露出を許可）。所有者チェックは FastAPI 側（他人のものは 404）。
 * どちらも CSRF 検証を先に行い、失敗は 403 で FastAPI へ到達させない。
 * Next.js 16 では `params` が Promise なので必ず await する。
 */

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

/** item_id は正の整数のみ。それ以外は 404（存在しない扱い） */
function parseItemId(raw: string): number | null {
  if (!/^\d{1,18}$/.test(raw)) return null;
  const n = Number(raw);
  return n > 0 ? n : null;
}

export async function PATCH(request: Request, ctx: Ctx) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const { id } = await ctx.params;
  const itemId = parseItemId(id);
  if (itemId === null) return Response.json({ code: "not_found" }, { status: 404 });

  const body = await readJsonBody(request);
  const quantity = body?.quantity;
  if (!Number.isInteger(quantity) || (quantity as number) <= 0) {
    return validationError([{ name: "quantity", reason: "out_of_range" }]);
  }

  return proxyCartRequest(request, `/cart/items/${itemId}`, { method: "PATCH", json: { quantity } });
}

export async function DELETE(request: Request, ctx: Ctx) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const { id } = await ctx.params;
  const itemId = parseItemId(id);
  if (itemId === null) return Response.json({ code: "not_found" }, { status: 404 });

  return proxyCartRequest(request, `/cart/items/${itemId}`, { method: "DELETE" });
}
