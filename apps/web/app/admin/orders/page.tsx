import type { Metadata } from "next";
import AdminOrderFilters from "@/components/admin/AdminOrderFilters";
import AdminOrderTable from "@/components/admin/AdminOrderTable";
import AdminPager from "@/components/admin/AdminPager";
import LoadError from "@/components/LoadError";
import { adminErrorMessage } from "@/lib/admin-messages";
import { parseOrderQuery } from "@/lib/admin-query";
import { loadAdminOrders, requireAdmin } from "@/lib/server/admin";

/**
 * 注文一覧 DS-SCR-015-3（設計仕様書 P2 追補c 6.5、テスト UT-WEB-46・UT-WEB-54・AT-33）。
 * 検索条件は URL のクエリに載せる。日付・注文番号・メールの形が違う入力は FastAPI に渡さず、フォームの項目にエラーを出す。
 * 氏名・電話・住所は一覧に出さない（API も返さない）。未ログイン・セッション失効は lib/server/admin.ts が `/admin/login` へ redirect する。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "注文 | 管理 | GU EC サイト", robots: { index: false, follow: false } };

export default async function AdminOrdersPage({ searchParams }: PageProps<"/admin/orders">) {
  const query = parseOrderQuery(await searchParams);
  // 検索条件に誤りがあるときは一覧を取らないが、未ログインで画面を見せないよう管理者の確認だけは行う
  if (query.apiQuery === null) await requireAdmin();
  const result = query.apiQuery === null ? null : await loadAdminOrders(query.apiQuery);

  // FastAPI が 400・422（期間が 366 日を超える等）を返したときは、一覧を出さず文言をフォームに出す
  const apiError =
    result && result.kind === "error" && (result.status === 400 || result.status === 422) ? adminErrorMessage(result.status, result.body) : null;

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-light tracking-heading">注文</h1>
      <AdminOrderFilters query={query} apiError={apiError} />
      {result === null || apiError ? null : result.kind === "ok" ? (
        <>
          <AdminOrderTable items={result.data.items} />
          <AdminPager
            basePath="/admin/orders"
            linkParams={query.linkParams}
            page={result.data.page}
            perPage={result.data.per_page}
            total={result.data.total}
            hasMore={result.data.has_more}
          />
        </>
      ) : (
        <LoadError what="注文" />
      )}
    </div>
  );
}
