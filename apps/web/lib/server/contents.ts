import "server-only";

import { apiFetch, type ApiResult } from "@/lib/server/api";
import type { ContentDetail, ContentKind, ContentsResponse } from "@/lib/types";

/**
 * コンテンツ系（DS-API-005・006）のデータ取得。設計仕様書 P2 追補a 1 章:
 * 「コンテンツ系は Server Component から FastAPI を直接呼ぶため BFF は追加しない」。
 * 一覧では `kind` は `feature`／`news` のみ受け付ける（`faq`／`static` は一覧化しない設計）。
 */

export function getContents(
  kind: Extract<ContentKind, "feature" | "news">,
  limit?: number,
): Promise<ApiResult<ContentsResponse>> {
  const sp = new URLSearchParams({ kind });
  if (limit !== undefined) sp.set("limit", String(limit));
  return apiFetch<ContentsResponse>(`/contents?${sp.toString()}`);
}

export function getContent(slug: string): Promise<ApiResult<ContentDetail>> {
  return apiFetch<ContentDetail>(`/contents/${encodeURIComponent(slug)}`);
}
