import Breadcrumb from "@/components/Breadcrumb";
import LoadError from "@/components/LoadError";
import SearchResults from "@/components/SearchResults";
import { getImageBaseUrl, loadOrNull } from "@/lib/server/catalog";
import { getSearch } from "@/lib/server/search";

/**
 * 検索結果 DS-SCR-002（検索モード。設計仕様書 P2 追補a 6.2、テスト AT-09・AT-10・ST-F003 系）。
 * `searchParams`（q・page）で DS-API-004 を呼ぶ。初回表示は Server Component から FastAPI を直接呼び、
 * 「もっと見る」だけ BFF（`/api/search`）を経由する（1 章の原則）。Next.js 16 では searchParams が Promise。
 */

export const dynamic = "force-dynamic";

function pickQuery(v: string | string[] | undefined): string {
  const s = Array.isArray(v) ? v[0] : v;
  return (s ?? "").slice(0, 100);
}

export default async function SearchPage({ searchParams }: PageProps<"/search">) {
  const sp = await searchParams;
  const q = pickQuery(sp.q);
  const pageRaw = Array.isArray(sp.page) ? sp.page[0] : sp.page;
  const page = pageRaw && /^\d{1,3}$/.test(pageRaw) ? Math.max(1, Number(pageRaw)) : 1;

  const crumbs = [{ label: "ホーム", href: "/" }, { label: "検索結果" }];

  if (q.trim().length === 0) {
    return (
      <div className="space-y-6">
        <Breadcrumb items={crumbs} />
        <p className="py-10 text-center text-sm text-fg-muted">検索語を入力してください。</p>
      </div>
    );
  }

  const result = await loadOrNull(getSearch({ q, page, per_page: 24 }), "search");
  const imageBaseUrl = getImageBaseUrl();

  return (
    <div className="space-y-6">
      <Breadcrumb items={crumbs} />

      {result === null ? (
        <LoadError what="検索結果" />
      ) : (
        <>
          <div className="flex items-baseline justify-between">
            <h1 className="text-xl font-light tracking-heading">「{result.query}」の検索結果</h1>
            <p className="text-sm text-fg-muted" data-testid="search-total">
              {result.total.toLocaleString("ja-JP")} 件
            </p>
          </div>
          <SearchResults
            key={`${result.query}:${page}`}
            query={result.query}
            initialItems={result.items}
            initialPage={result.page}
            hasMore={result.has_more}
            total={result.total}
            similarKeywords={result.similar_keywords}
            recommendedCategories={result.recommended_categories}
            imageBaseUrl={imageBaseUrl}
          />
        </>
      )}
    </div>
  );
}
