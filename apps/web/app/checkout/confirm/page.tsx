import type { Metadata } from "next";
import Breadcrumb from "@/components/Breadcrumb";
import OrderConfirm from "@/components/OrderConfirm";
import { getImageBaseUrl } from "@/lib/server/catalog";

/**
 * 注文確認 DS-SCR-006（確認）（設計仕様書 6.8）。本体は OrderConfirm（クライアント）。
 * 画像 URL の base（公開 URL）だけサーバーから渡す。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "ご注文内容の確認 | GU EC サイト" };

export default function CheckoutConfirmPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb
        items={[
          { label: "ホーム", href: "/" },
          { label: "カート", href: "/cart" },
          { label: "ご注文手続き", href: "/checkout" },
          { label: "ご注文内容の確認" },
        ]}
      />
      <OrderConfirm imageBaseUrl={getImageBaseUrl()} />
    </div>
  );
}
