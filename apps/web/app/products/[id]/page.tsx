import { notFound } from "next/navigation";
import Breadcrumb from "@/components/Breadcrumb";
import LoadError from "@/components/LoadError";
import Price from "@/components/Price";
import ProductCard from "@/components/ProductCard";
import PurchasePanel from "@/components/PurchasePanel";
import { imageUrl } from "@/lib/image";
import { UpstreamUnavailableError } from "@/lib/server/api";
import { getImageBaseUrl, getProduct } from "@/lib/server/catalog";

/**
 * 商品詳細 DS-SCR-003（設計仕様書 6.5・U-05・REQ-FR-1203、テスト ST-F005-01〜03・AT-03、デザイン基準 v1 4 章 SCR-003）。
 * 画像（複数）・名称・税込価格（--text-2xl・700）・色/サイズ/数量（PurchasePanel）・説明・素材・関連商品。
 * FastAPI の 404 は notFound()、接続不可は「読み込めませんでした」。Next.js 16 では params が Promise。
 * 375px では PurchasePanel の下部固定バーに隠れないよう本文下に余白を取る。
 */

export const dynamic = "force-dynamic";

const headingClass = "text-xl font-light tracking-heading";

export default async function ProductDetailPage({ params }: PageProps<"/products/[id]">) {
  const { id } = await params;
  if (!/^\d{1,18}$/.test(id)) notFound();

  let result;
  try {
    result = await getProduct(id);
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) {
      return <LoadError what="商品情報" />;
    }
    throw err;
  }
  if (!result.ok) {
    if (result.status === 404) notFound();
    console.error("[products/[id]] failed", { status: result.status, code: result.error.code });
    return <LoadError what="商品情報" />;
  }

  const product = result.data;
  const imageBaseUrl = getImageBaseUrl();
  const images = product.images.length > 0 ? product.images : [""];

  return (
    <article className="space-y-12 pb-28 sm:pb-0">
      <Breadcrumb items={[{ label: "ホーム", href: "/" }, { label: "商品一覧", href: "/products" }, { label: product.name }]} />

      <div className="grid gap-6 md:grid-cols-2">
        {/* 画像（複数枚は横スクロール。スナップで 1 枚ずつ） */}
        <section aria-label="商品画像">
          <ul className="flex snap-x snap-mandatory gap-2 overflow-x-auto rounded-sm">
            {images.map((path, i) => (
              <li key={`${path}-${i}`} className="w-full shrink-0 snap-center">
                {/* eslint-disable-next-line @next/next/no-img-element -- プレースホルダー PNG を素直に表示 */}
                <img
                  src={imageUrl(imageBaseUrl, path) ?? undefined}
                  alt={`${product.name} 画像 ${i + 1}/${images.length}`}
                  className="aspect-[3/4] w-full rounded-sm bg-line/50 object-cover"
                />
              </li>
            ))}
          </ul>
          {images.length > 1 && (
            <p className="mt-1 text-center text-xs text-fg-muted">横にスワイプして {images.length} 枚の画像を見る</p>
          )}
        </section>

        {/* 名称・価格・購入操作 */}
        <section className="space-y-6">
          <div>
            <h1 className={headingClass}>{product.name}</h1>
            <p className="mt-2 text-2xl font-bold tracking-heading text-fg">
              <Price amount={product.price_incl_tax} taxNote />
            </p>
          </div>
          <PurchasePanel
            productId={product.id}
            price={product.price_incl_tax}
            colors={product.colors}
            sizes={product.sizes}
            variants={product.variants}
          />
        </section>
      </div>

      <section aria-labelledby="desc-heading" className="space-y-4 text-sm">
        <h2 id="desc-heading" className={headingClass}>
          商品説明
        </h2>
        <p className="whitespace-pre-line">{product.description}</p>
        <h3 className="font-bold">素材</h3>
        <p className="whitespace-pre-line">{product.material}</p>
        <h3 className="font-bold">サイズ</h3>
        <ul className="flex flex-wrap gap-2">
          {product.sizes.map((s) => (
            <li key={s} className="rounded-pill border border-line px-3 py-1">
              {s}
            </li>
          ))}
        </ul>
      </section>

      {product.related.length > 0 && (
        <section aria-labelledby="related-heading">
          <h2 id="related-heading" className={`mb-4 ${headingClass}`}>
            関連商品
          </h2>
          <ul className="grid grid-cols-2 gap-x-2 gap-y-6 sm:grid-cols-4" aria-label="関連商品">
            {product.related.map((p) => (
              <li key={p.id}>
                <ProductCard
                  id={p.id}
                  name={p.name}
                  price={p.price_incl_tax}
                  imagePath={p.image_path}
                  imageBaseUrl={imageBaseUrl}
                  soldOut={p.sold_out}
                />
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
