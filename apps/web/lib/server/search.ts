import "server-only";

import { apiFetch, type ApiResult } from "@/lib/server/api";
import type { SearchResponse } from "@/lib/types";

/**
 * 商品検索（DS-API-004）のデータ取得。設計仕様書 P2 追補a 1 章の原則どおり、
 * `/search` の初回表示は Server Component から FastAPI を直接呼ぶ（BFF を経由しない）。
 * ブラウザからの「もっと見る」だけが BFF（`/api/search`）を経由する（本編 DS-DEC-06）。
 */

export interface SearchQuery {
  q: string;
  page?: number;
  per_page?: number;
}

/** `q=&page=&per_page=` のクエリ文字列（page を含まないバージョンは `buildSearchQueryWithoutPage`） */
export function buildSearchQuery(q: SearchQuery): string {
  const sp = new URLSearchParams();
  sp.set("q", q.q);
  sp.set("page", String(q.page ?? 1));
  sp.set("per_page", String(q.per_page ?? 24));
  return sp.toString();
}

/** 「もっと見る」でページ番号だけ差し替えるための、`q`（と `per_page`）だけの文字列 */
export function buildSearchQueryWithoutPage(q: string, per_page = 24): string {
  const sp = new URLSearchParams({ q, per_page: String(per_page) });
  return sp.toString();
}

export function getSearch(q: SearchQuery): Promise<ApiResult<SearchResponse>> {
  return apiFetch<SearchResponse>(`/search?${buildSearchQuery(q)}`);
}
