"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import Button, { buttonClass } from "@/components/Button";
import { TextField } from "@/components/Form";
import { AmountSummary, OrderItemsList, PickupCodeBlock, ShippingSummary } from "@/components/OrderSummary";
import { isValidEmail } from "@/lib/checkout-validation";
import { clearCheckoutSession, LAST_ORDER_KEY, saveLastOrder } from "@/lib/checkout-session";
import { parseJsonOrNull, useHydrated, useSessionItem } from "@/lib/client/use-session-item";
import { CartApiError } from "@/lib/client/cart-api";
import { lookupOrder } from "@/lib/client/order-api";
import { formatJst } from "@/lib/datetime";
import { isOrderNumber, lookupErrorMessage } from "@/lib/order-errors";
import type { OrderResponse } from "@/lib/types";

/**
 * 注文完了 DS-SCR-006（完了）（設計仕様書 6.8、テスト AT-01・AT-06・ST-F014-01・ST-F025-01/02、デザイン基準 v1 4 章 SCR-006）。
 * - sessionStorage（guapp.lastOrder）に注文があり URL の `n` と一致すれば再掲: 見出し・注文番号（--text-xl・700）・メール案内・
 *   注文内容・金額・お届け先・「買い物を続ける」（/ へ。次の追加は新しいカートに入る＝AT-06）
 * - 無ければ照会フォーム（注文番号＝URL の `n`、メール入力 → `POST /api/orders/[n]/lookup`）。404 は「注文番号かメールアドレスが違います」の
 *   一括表示、429 は「しばらくしてからお試しください」
 * - P2-b（設計仕様書 6.8）: 店舗受け取り（`receive_method=store`）は注文番号の下に受け取りコードを大きく表示し（API が返したときだけ）、
 *   店舗名・住所を出す。`is_member_order` が真なら「マイページの注文履歴で確認できます」、偽なら「ゲストでのご注文です…」を添える。
 *   照会フォームの結果も同じ形
 * - `ordered_at`（UTC）は JST で表示
 */

export interface OrderCompleteProps {
  /** URL の `n`。形式が違うものはページ側で null にしてある */
  orderNumber: string | null;
}

export default function OrderComplete({ orderNumber }: OrderCompleteProps) {
  const [found, setFound] = useState<OrderResponse | null>(null);
  const loaded = useHydrated();
  const raw = useSessionItem(LAST_ORDER_KEY);
  const stored = useMemo(() => {
    const v = parseJsonOrNull<OrderResponse>(raw);
    if (!v || typeof v.order_number !== "string" || !Array.isArray(v.items)) return null;
    // 別の注文番号で開かれたら（2 タブ等）保存済みの注文は使わず照会に回す
    if (orderNumber !== null && v.order_number !== orderNumber) return null;
    return v;
  }, [raw, orderNumber]);
  const order = found ?? stored;

  // 完了画面に来たら注文手続きの持ち回り（配送先・冪等キー）は不要。確定の成否に関わらず消す
  useEffect(() => {
    if (loaded) clearCheckoutSession();
  }, [loaded]);

  if (!loaded) {
    return (
      <p role="status" className="py-12 text-center text-sm text-fg-muted">
        読み込み中…
      </p>
    );
  }

  if (!order) {
    return (
      <LookupForm
        orderNumber={orderNumber}
        onFound={(o) => {
          saveLastOrder(o);
          setFound(o);
        }}
      />
    );
  }

  return <CompletedOrder order={order} />;
}

function CompletedOrder({ order }: { order: OrderResponse }) {
  const failed = order.status === "payment_failed";
  const isStore = order.receive_method === "store";
  return (
    <div className="space-y-8">
      <section className="space-y-3 text-center" aria-labelledby="complete-heading">
        <h1 id="complete-heading" className="text-xl font-light tracking-heading">
          {failed ? "この注文は決済に失敗しています" : "ご注文ありがとうございます"}
        </h1>
        <p className="text-sm text-fg-muted">注文番号</p>
        <p className="text-xl font-bold tracking-heading" data-testid="order-number">
          <span className="select-all">{order.order_number}</span>
        </p>
        <p className="text-sm text-fg-muted">注文日時 {formatJst(order.ordered_at)}（日本時間）</p>
        {!failed && isStore && order.pickup_code && (
          <div className="mx-auto max-w-xl">
            <PickupCodeBlock
              code={order.pickup_code}
              note="ご来店時にこのコードと注文番号をお伝えください。マイページ（会員のとき）でも確認できます"
            />
          </div>
        )}
        {!failed && (
          <div className="mx-auto max-w-xl rounded-sm border border-line bg-line/40 p-4 text-left text-sm">
            <p>{order.guest_email} に確認メールを送りました。</p>
            {order.is_member_order === true && (
              <p className="mt-1" data-testid="member-order-note">
                ご注文はマイページの注文履歴で確認できます。
              </p>
            )}
            {order.is_member_order === false && (
              <p className="mt-1" data-testid="guest-order-note">
                ゲストでのご注文です。注文番号とメールアドレスで照会できます。
              </p>
            )}
            <p className="mt-1 text-xs text-fg-muted">
              テスト環境ではメールは送信されず、サーバー側に保存されます。ゲストの方はこの画面を保存してください（注文番号とメールアドレスで後から照会できます）。
            </p>
          </div>
        )}
      </section>

      <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
        <div className="space-y-8">
          <section aria-labelledby="items-heading" className="space-y-2">
            <h2 id="items-heading" className="text-lg font-light tracking-heading">
              注文内容
            </h2>
            <OrderItemsList items={order.items} />
          </section>
          <section aria-labelledby="ship-heading" className="space-y-3">
            <h2 id="ship-heading" className="text-lg font-light tracking-heading">
              {isStore ? "受け取り・お支払い" : "お届け先・お支払い"}
            </h2>
            <ShippingSummary {...order} />
          </section>
        </div>
        <div className="space-y-4 lg:h-fit">
          <AmountSummary
            subtotal={order.subtotal}
            shipping_fee={order.shipping_fee}
            total={order.total}
            tax_included={order.tax_included}
            receiveMethod={order.receive_method}
          />
          <Link href="/" className={buttonClass({ variant: "primary", size: "lg", full: true })} data-testid="continue-shopping">
            買い物を続ける
          </Link>
        </div>
      </div>
    </div>
  );
}

function LookupForm({ orderNumber, onFound }: { orderNumber: string | null; onFound: (o: OrderResponse) => void }) {
  const [number, setNumber] = useState(orderNumber ?? "");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (busy) return;
    const n = number.trim().toUpperCase();
    const em = email.trim();
    if (!isOrderNumber(n) || !isValidEmail(em)) {
      // 形式不備も「違います」に寄せ、番号の存在をにおわせない
      setError("注文番号かメールアドレスが違います");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      onFound(await lookupOrder(n, em));
    } catch (err) {
      const status = err instanceof CartApiError ? err.status : 0;
      const body = err instanceof CartApiError ? err.body : null;
      setError(lookupErrorMessage(status, body));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-md space-y-6">
      <h1 className="text-xl font-light tracking-heading">ご注文の確認</h1>
      <p className="text-sm text-fg-muted">注文番号と、ご注文時のメールアドレスを入力してください。</p>
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <TextField
          id="lookup-number"
          label="注文番号"
          required
          placeholder="例: GU-260918-ABCDEFGH"
          value={number}
          onChange={(e) => setNumber(e.target.value)}
          autoComplete="off"
        />
        <TextField
          id="lookup-email"
          label="メールアドレス"
          required
          type="email"
          inputMode="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        {error && (
          <p role="alert" className="text-sm font-bold text-danger" data-testid="lookup-error">
            ⚠ {error}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" full busy={busy} busyLabel="確認中…">
          注文を表示する
        </Button>
      </form>
      <Link href="/" className={buttonClass({ variant: "secondary", size: "lg", full: true })}>
        買い物を続ける
      </Link>
    </div>
  );
}
