import type { Metadata } from "next";
import Breadcrumb from "@/components/Breadcrumb";
import CheckoutForm from "@/components/CheckoutForm";

/**
 * 注文手続き DS-SCR-005（設計仕様書 6.7）。フォーム本体は CheckoutForm（クライアント）。
 * 入力値はサーバーに置かず、prepare 応答と一緒に sessionStorage で確認画面へ渡す。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "ご注文手続き | GU EC サイト" };

export default function CheckoutPage() {
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: "ホーム", href: "/" }, { label: "カート", href: "/cart" }, { label: "ご注文手続き" }]} />
      <CheckoutForm />
    </div>
  );
}
