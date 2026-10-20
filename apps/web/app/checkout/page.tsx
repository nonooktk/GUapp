import type { Metadata } from "next";
import Breadcrumb from "@/components/Breadcrumb";
import CheckoutForm from "@/components/CheckoutForm";
import { getMemberOrNull } from "@/lib/server/member";
import { getStores } from "@/lib/server/stores";

/**
 * 注文手続き DS-SCR-005（設計仕様書 6.7）。フォーム本体は CheckoutForm（クライアント）。
 * 入力値はサーバーに置かず、prepare 応答と一緒に sessionStorage で確認画面へ渡す。
 * P2-b: ログイン中なら `GET /me` の氏名・メールをフォームの初期値に渡す（失効・未ログイン・接続不可は null＝ゲスト）。
 * 受け取り店舗は `GET /stores` で取得して渡す（失敗は null＝店舗受け取りを選べない）。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "ご注文手続き | GU EC サイト" };

export default async function CheckoutPage() {
  const [me, stores] = await Promise.all([getMemberOrNull(), getStores()]);
  return (
    <div className="space-y-6">
      <Breadcrumb items={[{ label: "ホーム", href: "/" }, { label: "カート", href: "/cart" }, { label: "ご注文手続き" }]} />
      <CheckoutForm member={me ? { name: me.name, email: me.email } : null} stores={stores} />
    </div>
  );
}
