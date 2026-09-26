import { apiFetch, UpstreamUnavailableError } from "@/lib/server/api";
import type { SuggestResponse } from "@/lib/types";

/**
 * 検索サジェスト BFF（DS-API-004a 取り次ぎ）。入力中のドロップダウンがブラウザから呼ぶ
 * （設計仕様書 P2 追補a 3.2・1 章）。受け付けるクエリは q のみ。
 */

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const sp = new URL(request.url).searchParams;
  const q = sp.get("q") ?? "";

  try {
    const result = await apiFetch<SuggestResponse>(`/search/suggest?${new URLSearchParams({ q }).toString()}`);
    if (!result.ok) {
      return Response.json(result.error, { status: result.status, headers: { "Cache-Control": "no-store" } });
    }
    return Response.json(result.data, { status: 200, headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) {
      return Response.json({ code: "upstream_unavailable" }, { status: 503 });
    }
    console.error("[api/search/suggest] unexpected error", err instanceof Error ? err.message : err);
    return Response.json({ code: "internal_error", message: "処理中にエラーが発生しました" }, { status: 500 });
  }
}
