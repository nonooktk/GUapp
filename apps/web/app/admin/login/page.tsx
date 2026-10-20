import type { Metadata } from "next";
import { redirect } from "next/navigation";
import AdminLoginForm from "@/components/admin/AdminLoginForm";
import { ADMIN_HOME_PATH } from "@/lib/admin-types";
import { firstParam } from "@/lib/safe-next";
import { getAdminOrNull } from "@/lib/server/admin";

/**
 * 管理ログイン DS-SCR-014（設計仕様書 P2 追補c 6.3、テスト UT-WEB-42・AT-30）。
 * すでにログイン済み（`GET /admin/me` が 200）なら `/admin/products` へ移す。Cookie `asid` が「ある」だけでは移さない
 * （失効した値が残っていると戻り合うため。会員のログイン画面と同じ）。遷移先の指定（`next`）は受けない。
 * `?expired=1` のときは有効期限切れの案内を出す。Next.js 16 では searchParams が Promise。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "管理者ログイン | GU EC サイト", robots: { index: false, follow: false } };

export default async function AdminLoginPage({ searchParams }: PageProps<"/admin/login">) {
  const sp = await searchParams;
  const expired = firstParam(sp.expired) === "1";

  const admin = await getAdminOrNull();
  if (admin) redirect(ADMIN_HOME_PATH);

  return <AdminLoginForm expired={expired} />;
}
