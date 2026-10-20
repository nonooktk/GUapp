import "server-only";

import { apiFetch } from "@/lib/server/api";
import { loadOrNull } from "@/lib/server/catalog";
import type { StoreSummary, StoresResponse } from "@/lib/types";

/**
 * 受け取り店舗の一覧（DS-API-026 `GET /stores`。認証不要）。Server Component（`/checkout`）が取得し、フォームへ props で渡す
 * （BFF の窓口は無い。設計仕様書 4.3）。取得に失敗したときは null を返し、画面は店舗受け取りを選べなくする。
 */
export async function getStores(): Promise<StoreSummary[] | null> {
  const data = await loadOrNull(apiFetch<StoresResponse>("/stores"), "stores");
  return data ? data.items : null;
}
