"use client";

import { useState } from "react";
import Button from "@/components/Button";
import ProductCard from "@/components/ProductCard";
import { fetchProductsPage } from "@/lib/client/cart-api";
import type { ProductSummary } from "@/lib/types";

/**
 * 商品一覧のグリッド＋「もっと見る」（設計仕様書 6.4・ST-F001-03、デザイン基準 v1 4 章 SCR-002）。
 * 初回 24 件はサーバーが描き、以降はクライアントが `GET /api/products?...&page=n+1` を呼んで末尾に追加する。
 * 375px で 2 列、sm で 3 列、lg で 4 列。列間 8px・縦 24px。「もっと見る」は secondary・中央寄せ・最大 320px。
 */

export interface ProductsGridProps {
  initialItems: ProductSummary[];
  initialPage: number;
  hasMore: boolean;
  total: number;
  /** `gender=women&category=tops` の形（page を含まない） */
  query: string;
  imageBaseUrl: string;
}

export default function ProductsGrid({ initialItems, initialPage, hasMore, total, query, imageBaseUrl }: ProductsGridProps) {
  const [items, setItems] = useState(initialItems);
  const [page, setPage] = useState(initialPage);
  const [more, setMore] = useState(hasMore);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMore = async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await fetchProductsPage(query, page + 1);
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

  if (items.length === 0) {
    return <p className="py-10 text-center text-sm text-fg-muted">該当する商品がありません</p>;
  }

  return (
    <div>
      <ul className="grid grid-cols-2 gap-x-2 gap-y-6 sm:grid-cols-3 lg:grid-cols-4" aria-label="商品一覧">
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
