import type { Metadata } from "next";
import OrderComplete from "@/components/OrderComplete";
import { isOrderNumber } from "@/lib/order-errors";

/**
 * 注文完了 DS-SCR-006（完了）（設計仕様書 6.8）。`?n=GU-YYMMDD-XXXXXXXX` の注文番号を受け取り、
 * 本体（OrderComplete・クライアント）が sessionStorage の注文を再掲する。無ければ照会フォーム。
 * Next.js 16 では searchParams が Promise。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "ご注文完了 | GU EC サイト" };

export default async function OrderCompletePage({ searchParams }: PageProps<"/orders/complete">) {
  const sp = await searchParams;
  const raw = Array.isArray(sp.n) ? sp.n[0] : sp.n;
  const orderNumber = isOrderNumber(raw) ? raw : null;
  return <OrderComplete orderNumber={orderNumber} />;
}
