"use client";

import Link from "next/link";
import { useState } from "react";
import Button from "@/components/Button";
import ProductCard from "@/components/ProductCard";
import { fetchSearchPage } from "@/lib/client/search-api";
import type { ProductSummary, RecommendedCategory } from "@/lib/types";

/**
 * 検索結果グリッド＋0 件時の代替導線（DS-SCR-002 検索モード、設計仕様書 P2 追補a 6.2）。
 * 「もっと見る」は `ProductsGrid` と同じ方式で BFF（`/api/search`）から追加取得する。
 * 0 件時は `similar_keywords`（無ければ行自体を出さない）・`recommended_categories` を出す。
 */

export interface SearchResultsProps {
  query: string;
  initialItems: ProductSummary[];
  initialPage: number;
  hasMore: boolean;
  total: number;
  similarKeywords: string[];
  recommendedCategories: RecommendedCategory[];
  imageBaseUrl: string;
}

export default function SearchResults({
  query,
  initialItems,
  initialPage,
  hasMore,
  total,
  similarKeywords,
  recommendedCategories,
  imageBaseUrl,
}: SearchResultsProps) {
  const [items, setItems] = useState(initialItems);
  const [page, setPage] = useState(initialPage);
  const [more, setMore] = useState(hasMore);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMore = async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await fetchSearchPage(query, page + 1);
      setItems((prev) => {
        const seen = new Set(prev.map((p) => p.id));
        return [...prev, ...next.items.filter((p) => !seen.has(p.id))];
      });
      setPage(next.page);
      setMore(next.has_more);
    } catch {
      setError("読み込めませんでした。もう一度お試しください");
    } finally {
      setLoading(false);
    }
  };

  if (total === 0) {
    return (
      <div className="space-y-8 py-6">
        <p className="text-center text-sm text-fg-muted">該当する商品が見つかりませんでした。</p>
        {similarKeywords.length > 0 && (
          <section aria-labelledby="similar-keywords-heading" className="text-center">
            <h2 id="similar-keywords-heading" className="mb-3 text-sm font-bold text-fg">
              もしかして
            </h2>
            <ul className="flex flex-wrap justify-center gap-2">
              {similarKeywords.map((keyword) => (
                <li key={keyword}>
                  <Link
                    href={`/search?q=${encodeURIComponent(keyword)}`}
                    className="inline-flex h-11 items-center rounded-pill border border-line px-4 text-sm text-fg hover:bg-line"
                  >
                    {keyword}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
        {recommendedCategories.length > 0 && (
          <section aria-labelledby="recommended-categories-heading" className="text-center">
            <h2 id="recommended-categories-heading" className="mb-3 text-sm font-bold text-fg">
              おすすめのカテゴリ
            </h2>
            <ul className="flex flex-wrap justify-center gap-2">
              {recommendedCategories.map((c) => (
                <li key={c.slug}>
                  <Link
                    href={`/products?category=${encodeURIComponent(c.slug)}`}
                    className="inline-flex h-11 items-center rounded-pill border border-line px-4 text-sm text-fg hover:bg-line"
                  >
                    {c.name}
                    <span className="ml-1 text-xs text-fg-muted">{c.product_count}件</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    );
  }

  return (
    <div>
      <ul className="grid grid-cols-2 gap-x-2 gap-y-6 sm:grid-cols-3 lg:grid-cols-4" aria-label="検索結果">
        {items.map((p) => (
          <li key={p.id}>
            <ProductCard
              id={p.id}
              name={p.name}
              price={p.price_incl_tax}
              imagePath={p.image_path}
              imageBaseUrl={imageBaseUrl}
              soldOut={p.sold_out}
              colors={p.colors}
            />
          </li>
        ))}
      </ul>
      <div className="mt-8 flex flex-col items-center gap-3">
        <p className="text-xs text-fg-muted" aria-live="polite">
          {items.length} / {total} 件を表示
        </p>
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        {more && (
          <Button variant="secondary" size="lg" onClick={loadMore} busy={loading} busyLabel="読み込み中…" className="w-full max-w-80">
            もっと見る
          </Button>
        )}
      </div>
    </div>
  );
}
