import { apiFetch, UpstreamUnavailableError } from "@/lib/server/api";
import { buildProductsQuery } from "@/lib/server/catalog";
import type { ProductListResponse } from "@/lib/types";

/**
 * 商品一覧 BFF（DS-API-002 取り次ぎ）。一覧画面の「もっと見る」がクライアントから呼ぶ（ST-F001-03）。
 * 受け付けるクエリは gender・category・page・per_page のみ。page は 1〜999、per_page は 1〜24 に丸める。
 */

export const dynamic = "force-dynamic";

const SLUG = /^[a-z0-9_-]{1,64}$/;

function clampInt(raw: string | null, fallback: number, min: number, max: number): number {
  if (raw === null || !/^\d+$/.test(raw)) return fallback;
  return Math.min(max, Math.max(min, Number(raw)));
}

export async function GET(request: Request) {
  const sp = new URL(request.url).searchParams;
  const gender = sp.get("gender");
  const category = sp.get("category");
  const query = buildProductsQuery({
    gender: gender && SLUG.test(gender) ? gender : undefined,
    category: category && SLUG.test(category) ? category : undefined,
    page: clampInt(sp.get("page"), 1, 1, 999),
    per_page: clampInt(sp.get("per_page"), 24, 1, 24),
  });

  try {
    const result = await apiFetch<ProductListResponse>(`/products?${query}`);
    if (!result.ok) {
      return Response.json(result.error, { status: result.status, headers: { "Cache-Control": "no-store" } });
    }
    return Response.json(result.data, { status: 200, headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) {
      return Response.json({ code: "upstream_unavailable" }, { status: 503 });
    }
    console.error("[api/products] unexpected error", err instanceof Error ? err.message : err);
    return Response.json({ code: "internal_error", message: "処理中にエラーが発生しました" }, { status: 500 });
  }
}
