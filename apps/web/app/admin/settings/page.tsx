import type { Metadata } from "next";
import AdminSettingsForm from "@/components/admin/AdminSettingsForm";
import LoadError from "@/components/LoadError";
import { loadAdminSettings } from "@/lib/server/admin";

/**
 * 設定 DS-SCR-016（設計仕様書 P2 追補c 6.6、テスト UT-WEB-48・AT-35）。消費税率・送料・送料無料の下限を更新する（削る順番④）。
 * クーポン・キャンペーンの設定は作らない（`coupons` 表が P3。DS-DEC-119）。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "設定 | 管理 | GU EC サイト", robots: { index: false, follow: false } };

export default async function AdminSettingsPage() {
  const result = await loadAdminSettings();
  if (result.kind !== "ok") return <LoadError what="設定" />;

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-light tracking-heading">設定</h1>
      <AdminSettingsForm items={result.data.items} />
    </div>
  );
}
