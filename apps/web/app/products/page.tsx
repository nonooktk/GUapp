import Breadcrumb, { type Crumb } from "@/components/Breadcrumb";
import CategoryNav from "@/components/CategoryNav";
import LoadError from "@/components/LoadError";
import ProductsGrid from "@/components/ProductsGrid";
import { genderLabel, isGenderSlug } from "@/lib/gender";
import { getCategories, getImageBaseUrl, getProducts, loadOrNull } from "@/lib/server/catalog";

/**
 * 商品一覧 DS-SCR-002（設計仕様書 6.4、テスト ST-F001-01/03・AT-07、デザイン基準 v1 4 章 SCR-002）。
 * `searchParams`（gender・category・page）で DS-API-002 を呼ぶ。24 件区切りで「もっと見る」はクライアントが追加取得。
 * パンくず（ホーム > WOMEN > トップス）・件数・商品カード。Next.js 16 では searchParams が Promise。
 */

export const dynamic = "force-dynamic";

const SLUG = /^[a-z0-9_-]{1,64}$/;

function pickString(v: string | string[] | undefined): string | undefined {
  const s = Array.isArray(v) ? v[0] : v;
  return s && SLUG.test(s) ? s : undefined;
}

export default async function ProductsPage({ searchParams }: PageProps<"/products">) {
  const sp = await searchParams;
  const gender = pickString(sp.gender);
  const category = pickString(sp.category);
  const pageRaw = Array.isArray(sp.page) ? sp.page[0] : sp.page;
  const page = pageRaw && /^\d{1,3}$/.test(pageRaw) ? Math.max(1, Number(pageRaw)) : 1;

  const [list, cats] = await Promise.all([
    loadOrNull(getProducts({ gender: isGenderSlug(gender) ? gender : undefined, category, page, per_page: 24 }), "products list"),
    loadOrNull(getCategories(), "categories"),
  ]);
  const imageBaseUrl = getImageBaseUrl();

  const categoryName = cats?.categories.flatMap((c) => c.children).find((c) => c.slug === category)?.name ?? category;
  const gLabel = genderLabel(gender);
  const query = new URLSearchParams({ ...(gender ? { gender } : {}), ...(category ? { category } : {}) }).toString();

  const crumbs: Crumb[] = [
    { label: "ホーム", href: "/" },
    gLabel ? { label: gLabel, href: `/products?gender=${gender}` } : { label: "すべての商品" },
    ...(categoryName ? [{ label: categoryName }] : []),
  ];

  return (
    <div className="space-y-6">
      <Breadcrumb items={crumbs} />

      <CategoryNav categories={cats?.categories ?? null} gender={gender} category={category} />

      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-light tracking-heading">
          {gLabel ?? "すべての商品"}
          {categoryName ? ` > ${categoryName}` : ""}
        </h1>
        {list && (
          <p className="text-sm text-fg-muted" data-testid="product-total">
            {list.total.toLocaleString("ja-JP")} 件
          </p>
        )}
      </div>

      {list === null ? (
        <LoadError what="商品一覧" />
      ) : (
        <ProductsGrid
          key={`${query}:${page}`}
          initialItems={list.items}
          initialPage={list.page}
          hasMore={list.has_more}
          total={list.total}
          query={query}
          imageBaseUrl={imageBaseUrl}
        />
      )}
    </div>
  );
}
