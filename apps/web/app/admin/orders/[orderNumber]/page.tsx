import type { Metadata } from "next";
import { notFound } from "next/navigation";
import AdminOrderDetail from "@/components/admin/AdminOrderDetail";
import LoadError from "@/components/LoadError";
import { loadAdminOrder } from "@/lib/server/admin";

/**
 * 注文詳細・状態の更新 DS-SCR-015-4（設計仕様書 P2 追補c 6.5・DS-DEC-118、テスト UT-WEB-47・AT-33・AT-34・ST-SEC-87）。
 * 詳細を開くと API が `audit_logs` に `admin.order.view` を記録する（個人情報の閲覧の記録）。注文番号の形が違う・存在しない場合は 404。
 * 受け取りコードは表示しない。電話は末尾 4 桁だけ。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "注文詳細 | 管理 | GU EC サイト", robots: { index: false, follow: false } };

export default async function AdminOrderPage({ params }: PageProps<"/admin/orders/[orderNumber]">) {
  const { orderNumber } = await params;
  const result = await loadAdminOrder(orderNumber);
  if (result.kind === "not_found") notFound();
  if (result.kind !== "ok") return <LoadError what="注文" />;

  return <AdminOrderDetail order={result.data} />;
}
