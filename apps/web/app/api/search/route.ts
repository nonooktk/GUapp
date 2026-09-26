import { apiFetch, UpstreamUnavailableError } from "@/lib/server/api";
import { buildSearchQuery } from "@/lib/server/search";
import type { SearchResponse } from "@/lib/types";

/**
 * 商品検索 BFF（DS-API-004 取り次ぎ）。検索結果画面の「もっと見る」がブラウザから呼ぶ
 * （設計仕様書 P2 追補a 1 章: ブラウザは FastAPI を直接呼ばない）。
 * 受け付けるクエリは q・page・per_page のみ。q は 1〜100 文字、page は 1〜999、per_page は 1〜24 に丸める。
 */

export const dynamic = "force-dynamic";

function clampInt(raw: string | null, fallback: number, min: number, max: number): number {
  if (raw === null || !/^\d+$/.test(raw)) return fallback;
  return Math.min(max, Math.max(min, Number(raw)));
}

/** 空文字・101 文字以上は FastAPI 側の 400 判定に委ねるため、そのまま渡す（切り詰めない） */
function pickQuery(raw: string | null): string {
  return raw ?? "";
}

export async function GET(request: Request) {
  const sp = new URL(request.url).searchParams;
  const query = buildSearchQuery({
    q: pickQuery(sp.get("q")),
    page: clampInt(sp.get("page"), 1, 1, 999),
    per_page: clampInt(sp.get("per_page"), 24, 1, 24),
  });

  try {
    const result = await apiFetch<SearchResponse>(`/search?${query}`);
    if (!result.ok) {
      return Response.json(result.error, { status: result.status, headers: { "Cache-Control": "no-store" } });
    }
    return Response.json(result.data, { status: 200, headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) {
      return Response.json({ code: "upstream_unavailable" }, { status: 503 });
    }
    console.error("[api/search] unexpected error", err instanceof Error ? err.message : err);
    return Response.json({ code: "internal_error", message: "処理中にエラーが発生しました" }, { status: 500 });
  }
}
