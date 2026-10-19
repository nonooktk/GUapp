import { proxyCartRequest, readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { isValidId, isValidQuantity } from "@/lib/request-validation";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * カート明細の数量変更・削除 BFF（DS-API-012/013 取り次ぎ）。
 * `[id]` は FastAPI の `item_id`（設計仕様書 7.5 の例外として露出を許可）。所有者チェックは FastAPI 側（他人のものは 404）。
 * どちらも CSRF 検証を先に行い、失敗は 403 で FastAPI へ到達させない。
 * 範囲は quantity が 1〜99 の整数、item_id が 1〜2^53-1（S7）。本文は 8KB まで（S2）。
 * Next.js 16 では `params` が Promise なので必ず await する。
 */

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

/**
 * item_id の解釈。数字以外は 404（存在しない扱い）。数字でも 1〜2^53-1 を外れたら 400 out_of_range（S7）。
 * 19 桁以上は桁数だけで範囲外とする（Number にすると丸まるため）。
 */
type ParsedItemId = { kind: "ok"; id: number } | { kind: "not_found" } | { kind: "out_of_range" };

function parseItemId(raw: string): ParsedItemId {
  if (!/^\d+$/.test(raw)) return { kind: "not_found" };
  if (raw.length > 16) return { kind: "out_of_range" };
  const n = Number(raw);
  return isValidId(n) ? { kind: "ok", id: n } : { kind: "out_of_range" };
}

function itemIdError(request: Request, parsed: Exclude<ParsedItemId, { kind: "ok" }>): Response {
  if (parsed.kind === "not_found") return Response.json({ code: "not_found" }, { status: 404 });
  return validationError(request, [{ name: "item_id", reason: "out_of_range" }]);
}

export async function PATCH(request: Request, ctx: Ctx) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const { id } = await ctx.params;
  const itemId = parseItemId(id);
  if (itemId.kind !== "ok") return itemIdError(request, itemId);

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  const quantity = parsed.body?.quantity;
  if (!isValidQuantity(quantity)) {
    return validationError(request, [{ name: "quantity", reason: "out_of_range" }]);
  }

  return proxyCartRequest(request, `/cart/items/${itemId.id}`, { method: "PATCH", json: { quantity } });
}

export async function DELETE(request: Request, ctx: Ctx) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const { id } = await ctx.params;
  const itemId = parseItemId(id);
  if (itemId.kind !== "ok") return itemIdError(request, itemId);

  return proxyCartRequest(request, `/cart/items/${itemId.id}`, { method: "DELETE" });
}
