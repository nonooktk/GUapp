import Link from "next/link";
import { buttonClass } from "@/components/Button";
import LoadError from "@/components/LoadError";
import ProductCard from "@/components/ProductCard";
import { GENDERS } from "@/lib/gender";
import { getImageBaseUrl, getProducts, loadOrNull } from "@/lib/server/catalog";

/**
 * ホーム DS-SCR-001（設計仕様書 6.3・U-01〜U-03、デザイン基準 v1 4 章 SCR-001）。
 * トップ画像（プレースホルダー）→ 性別カテゴリ（375px で 3 列）→ おすすめ商品（P1 は新着 8 件 = DS-API-002 page=1・per_page=8。
 * 375px 2 列／1280px 4 列）→ お知らせ（P1 は固定文）。FastAPI 停止時はおすすめ欄だけ「読み込めませんでした」。
 */

export const dynamic = "force-dynamic";

const NOTICES = [
  "【お知らせ】本サイトは演習用（P1）です。実際の注文・決済は行われません。",
  "【配送】4,990 円（税込）以上のご注文で送料無料。",
] as const;

const headingClass = "text-xl font-light tracking-heading";

export default async function HomePage() {
  const [recommended, imageBaseUrl] = await Promise.all([
    loadOrNull(getProducts({ page: 1, per_page: 8 }), "home recommended"),
    Promise.resolve(getImageBaseUrl()),
  ]);

  return (
    <div className="space-y-12">
      {/* トップ画像（U-01）: P1 はプレースホルダー（GU の写真・文言は使わない） */}
      <section aria-label="特集" className="relative overflow-hidden rounded-sm bg-linear-to-br from-fg to-fg-muted">
        <div className="flex h-48 flex-col items-center justify-center px-4 text-center text-bg sm:h-72">
          <p className="text-xs tracking-heading">2026 AUTUMN</p>
          <p className="mt-2 text-2xl font-light tracking-heading">NEW ARRIVALS</p>
          <Link href="/products" className={buttonClass({ variant: "secondary", size: "md", className: "mt-6 focus-visible:outline-bg" })}>
            すべての商品を見る
          </Link>
        </div>
      </section>

      {/* カテゴリ（U-02）: 375px でも 3 列 */}
      <section aria-labelledby="category-heading">
        <h2 id="category-heading" className={`mb-4 ${headingClass}`}>
          カテゴリ
        </h2>
        <ul className="grid grid-cols-3 gap-2">
          {GENDERS.map((g) => (
            <li key={g.slug}>
              <Link
                href={`/products?gender=${g.slug}`}
                className="flex h-20 items-center justify-center rounded-sm border border-line bg-bg px-1 text-center text-sm font-light tracking-heading hover:bg-line/40 sm:h-24 sm:text-base"
              >
                {g.label}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {/* おすすめ商品（U-03）: 新着 8 件 */}
      <section aria-labelledby="recommend-heading">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 id="recommend-heading" className={headingClass}>
            おすすめ商品
          </h2>
          <Link href="/products" className="inline-flex h-11 items-center text-sm text-fg-muted underline underline-offset-2 hover:no-underline">
            もっと見る
          </Link>
        </div>
        {recommended === null ? (
          <LoadError what="おすすめ商品" />
        ) : recommended.items.length === 0 ? (
          <p className="text-sm text-fg-muted">商品がまだ登録されていません</p>
        ) : (
          <ul className="grid grid-cols-2 gap-x-2 gap-y-6 sm:grid-cols-4" aria-label="おすすめ商品">
            {recommended.items.map((p) => (
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
        )}
      </section>

      {/* お知らせ（P1 は固定文） */}
      <section aria-labelledby="notice-heading">
        <h2 id="notice-heading" className={`mb-4 ${headingClass}`}>
          お知らせ
        </h2>
        <ul className="divide-y divide-line rounded-sm border border-line text-sm">
          {NOTICES.map((n) => (
            <li key={n} className="px-4 py-3">
              {n}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
