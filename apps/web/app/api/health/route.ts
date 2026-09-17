import { apiFetch, UpstreamUnavailableError } from "@/lib/server/api";

/**
 * BFF の疎通確認。FastAPI の `/api/v1/health` を内部トークン付きで呼び、結果を返す。
 * FastAPI が起動していなければ 503 `{code:"upstream_unavailable"}`。
 */

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const result = await apiFetch<unknown>("/health");
    if (!result.ok) {
      return Response.json(result.error, { status: result.status });
    }
    return Response.json({ status: "ok", upstream: result.data }, { status: 200 });
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) {
      return Response.json({ code: "upstream_unavailable" }, { status: 503 });
    }
    // 環境変数の不備など。詳細はログのみ（設計 4.5: 500 は固定文言）
    console.error("[api/health] unexpected error", err instanceof Error ? err.message : err);
    return Response.json({ code: "internal_error", message: "処理中にエラーが発生しました" }, { status: 500 });
  }
}
