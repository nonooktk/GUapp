import type { Metadata } from "next";
import AdminShell from "@/components/admin/AdminShell";
import { getAdminOrNull } from "@/lib/server/admin";

/**
 * 管理画面の共通レイアウト（設計仕様書 P2 追補c 6.2・DS-DEC-122、テスト UT-WEB-41・52）。
 * ルートレイアウトは `x-admin-area: 1`（proxy.ts が `/admin` 配下にだけ付ける）を読んで顧客向けの枠を省いている。ここでは管理画面の枠を出す。
 *
 * - `GET /admin/me`（DS-API-050b）で管理者を確認できたときだけ、見出し・メニュー・ログアウトのシェルを付ける
 * - 確認できない（`asid` が無い・失効・会員のセッション）ときはシェルを付けずに本文だけを出す。**本文のページは、どれも管理データの取得
 *   （lib/server/admin.ts）で 401・403 のとき `/admin/login` へ redirect する**ので、未ログインで内容が見えることはない。
 *   レイアウトで redirect しないのは、`/admin/login` 自身もこのレイアウトの下にあり（route group を使わない。DS-DEC-122）、
 *   Next.js のレイアウトは現在のパスを知らないため、redirect すると `/admin/login` が自分へ戻り続けるから
 * - 全ページ検索エンジンに載せない（metadata の robots。応答ヘッダー `X-Robots-Tag` は next.config.ts）。動的描画（Cookie を読む）
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "管理 | GU EC サイト",
  robots: { index: false, follow: false },
};

export default async function AdminLayout({ children }: LayoutProps<"/admin">) {
  const admin = await getAdminOrNull();
  if (!admin) {
    return (
      <main id="main" className="mx-auto w-full max-w-page flex-1 px-4 py-6">
        {children}
      </main>
    );
  }
  return <AdminShell loginId={admin.login_id}>{children}</AdminShell>;
}
