import type { Metadata } from "next";
import AdminPager from "@/components/admin/AdminPager";
import AdminProductFilters from "@/components/admin/AdminProductFilters";
import AdminProductTable from "@/components/admin/AdminProductTable";
import LoadError from "@/components/LoadError";
import { parseProductQuery } from "@/lib/admin-query";
import { loadAdminProducts } from "@/lib/server/admin";

/**
 * 商品一覧 DS-SCR-015-1（設計仕様書 P2 追補c 6.4、テスト UT-WEB-43・UT-WEB-54・AT-31）。
 * 検索条件は URL のクエリ（`?q=&visibility=&stock=&page=`）に載せ、ここで読む。条件に合わない値（列挙外・長すぎる値）は捨てて既定に戻し、
 * FastAPI へは検査済みの値だけを渡す。未ログイン・セッション失効（API が 401・403）は lib/server/admin.ts が `/admin/login` へ redirect する。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "商品 | 管理 | GU EC サイト", robots: { index: false, follow: false } };

export default async function AdminProductsPage({ searchParams }: PageProps<"/admin/products">) {
  const query = parseProductQuery(await searchParams);
  const result = await loadAdminProducts(query.apiQuery);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-light tracking-heading">商品</h1>
      <AdminProductFilters query={query} />
      {result.kind !== "ok" ? (
        <LoadError what="商品" />
      ) : (
        <>
          <AdminProductTable items={result.data.items} />
          <AdminPager
            basePath="/admin/products"
            linkParams={query.linkParams}
            page={result.data.page}
            perPage={result.data.per_page}
            total={result.data.total}
            hasMore={result.data.has_more}
          />
        </>
      )}
    </div>
  );
}
