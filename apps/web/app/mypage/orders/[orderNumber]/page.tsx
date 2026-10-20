import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Breadcrumb from "@/components/Breadcrumb";
import LoadError from "@/components/LoadError";
import OrderDetail from "@/components/OrderDetail";
import { isOrderNumber } from "@/lib/order-errors";
import { loadMyOrder } from "@/lib/server/member";

/**
 * 注文詳細（履歴） DS-SCR-009（設計仕様書 6.5・DS-API-024a、テスト AT-14・ST-F017-08・ST-SEC-47・48）。
 * 注文番号の形が違う・API が 404（他人の注文・ゲスト注文・不存在を区別しない）は `notFound()`。401 は `/login?next=/mypage` へ。
 * Next.js 16 では params が Promise。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "ご注文の詳細 | GU EC サイト", robots: { index: false } };

export default async function MyOrderPage({ params }: PageProps<"/mypage/orders/[orderNumber]">) {
  const { orderNumber } = await params;
  if (!isOrderNumber(orderNumber)) notFound();

  const result = await loadMyOrder(orderNumber);
  if (result.kind === "not_found") notFound();
  if (result.kind === "error") return <LoadError what="注文情報" />;

  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[{ label: "ホーム", href: "/" }, { label: "マイページ", href: "/mypage" }, { label: `注文 ${orderNumber}` }]}
      />
      <OrderDetail order={result.data} />
    </div>
  );
}
