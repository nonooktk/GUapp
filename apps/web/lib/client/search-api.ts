import type { SearchResponse, SuggestResponse } from "@/lib/types";

/**
 * ブラウザから検索系 BFF（`/api/search*`）を呼ぶ薄いクライアント。
 * 読み取り専用（GET のみ）のため CSRF トークンは不要（`lib/client/cart-api.ts` と異なる点）。
 */

export class SearchApiError extends Error {
  constructor(readonly status: number) {
    super(`search api ${status}`);
    this.name = "SearchApiError";
  }
}

async function getJson<T>(input: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(input, { method: "GET", cache: "no-store", signal });
  if (!res.ok) throw new SearchApiError(res.status);
  return (await res.json()) as T;
}

/** 検索結果の「もっと見る」。`page` を差し替えて次ページを取得する */
export function fetchSearchPage(q: string, page: number, perPage = 24): Promise<SearchResponse> {
  const sp = new URLSearchParams({ q, page: String(page), per_page: String(perPage) });
  return getJson<SearchResponse>(`/api/search?${sp.toString()}`);
}

/** 入力中のサジェスト（DS-API-004a）。呼び出し側で 300ms デバウンスする */
export function fetchSuggestions(q: string, signal?: AbortSignal): Promise<SuggestResponse> {
  const sp = new URLSearchParams({ q });
  return getJson<SuggestResponse>(`/api/search/suggest?${sp.toString()}`, signal);
}
