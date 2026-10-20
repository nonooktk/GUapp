import Link from "next/link";
import { buttonClass } from "@/components/Button";
import { AmountSummary, OrderItemsList, PickupCodeBlock, ShippingSummary } from "@/components/OrderSummary";
import { formatJst } from "@/lib/datetime";
import { formatStoreAddress } from "@/lib/format";
import type { OrderResponse, OrderStatus } from "@/lib/types";

/**
 * 注文詳細（履歴） DS-SCR-009（設計仕様書 6.5・DS-API-024a、テスト UT-WEB-22・AT-14・ST-F017）。
 * - 注文日（JST）・状態（`status_label`）・進捗バー・受け取り方法（店舗は店舗名・住所と受け取りコード、配送はお届け先と追跡番号）・明細・金額
 * - 進捗バーは `status` から決める。配送「受付 → 出荷準備 → 出荷済 → 配達完了」、店舗「受付 → 準備中 → 受け取り可能 → 受渡済」。
 *   pending_payment は 0 段、accepted 1、preparing 2、shipped 3、delivered 4 を完了とする。
 *   cancelled・pickup_expired・payment_failed は進捗バーを出さず、状態名のバッジだけを出す
 * - 受け取りコード・追跡番号は API が返したときだけ表示する（返さないときは枠ごと出さない）。コードは `ABCD-EFGH` の形に区切る
 * Server Component から描ける（フックなし）。
 */

export const DELIVERY_STEPS = ["受付", "出荷準備", "出荷済", "配達完了"] as const;
export const STORE_STEPS = ["受付", "準備中", "受け取り可能", "受渡済"] as const;

const PROGRESS: Partial<Record<OrderStatus, number>> = {
  pending_payment: 0,
  accepted: 1,
  preparing: 2,
  shipped: 3,
  delivered: 4,
};

/** 完了した段数。進捗バーを出さない状態（cancelled など）は null */
export function progressSteps(status: string): number | null {
  const n = PROGRESS[status as OrderStatus];
  return n === undefined ? null : n;
}

export function OrderProgress({ status, receiveMethod }: { status: string; receiveMethod: string }) {
  const done = progressSteps(status);
  if (done === null) return null;
  const steps = receiveMethod === "store" ? STORE_STEPS : DELIVERY_STEPS;
  return (
    <ol className="grid grid-cols-4 gap-1 text-center text-xs" aria-label="進捗" data-testid="order-progress" data-done={done}>
      {steps.map((label, i) => {
        const completed = i < done;
        const current = completed && i === done - 1;
        return (
          <li key={label} data-state={completed ? "done" : "todo"} aria-current={current ? "step" : undefined}>
            <span aria-hidden="true" className={`block h-1.5 rounded-pill ${completed ? "bg-fg" : "bg-line"}`} />
            <span className={`mt-1 block whitespace-nowrap ${completed ? "font-bold text-fg" : "text-fg-muted"}`}>
              <span aria-hidden="true" className="block leading-none">
                {completed ? "●" : "○"}
              </span>
              {label}
              <span className="sr-only">{completed ? "（完了）" : "（未完了）"}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export default function OrderDetail({ order }: { order: OrderResponse }) {
  const isStore = order.receive_method === "store";
  const label = order.status_label ?? order.status;
  const showProgress = progressSteps(order.status) !== null;

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <h1 className="text-xl font-light tracking-heading">ご注文の詳細</h1>
        <p className="text-lg font-bold tracking-heading" data-testid="order-number">
          <span className="select-all break-all">{order.order_number}</span>
        </p>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
          <p className="text-fg-muted">ご注文日 {formatJst(order.ordered_at)}（日本時間）</p>
          <p>
            状態:{" "}
            <span className="rounded-pill border border-fg px-3 text-xs font-bold" data-testid="order-status-label">
              {label}
            </span>
          </p>
        </div>
        {showProgress && <OrderProgress status={order.status} receiveMethod={order.receive_method} />}
      </header>

      {isStore && (
        <section aria-labelledby="store-heading" className="space-y-3 rounded-sm border border-line p-4">
          <h2 id="store-heading" className="text-lg font-light tracking-heading">
            受け取り方法: 店舗受け取り
          </h2>
          {order.store && (
            <p className="text-sm" data-testid="store-info">
              <span className="font-bold">{order.store.name}</span>
              <span className="mt-0.5 block break-words text-fg-muted">
                {formatStoreAddress(order.store)}
              </span>
            </p>
          )}
          {order.pickup_code && (
            <PickupCodeBlock code={order.pickup_code} note="ご来店時にこのコードと注文番号をお伝えください" />
          )}
        </section>
      )}

      <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
        <div className="space-y-8">
          <section aria-labelledby="items-heading" className="space-y-2">
            <h2 id="items-heading" className="text-lg font-light tracking-heading">
              ご注文内容
            </h2>
            <OrderItemsList items={order.items} />
          </section>
          <section aria-labelledby="ship-heading" className="space-y-3">
            <h2 id="ship-heading" className="text-lg font-light tracking-heading">
              {isStore ? "受け取り・お支払い" : "お届け先・お支払い"}
            </h2>
            <ShippingSummary {...order} store={null} />
            {!isStore && order.tracking_number && (
              <dl className="grid gap-1 text-sm sm:grid-cols-[8rem_1fr]" data-testid="tracking">
                <dt className="text-fg-muted">追跡番号</dt>
                <dd className="break-all font-bold">{order.tracking_number}</dd>
              </dl>
            )}
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
          <Link href="/mypage" className={buttonClass({ variant: "secondary", size: "lg", full: true })}>
            マイページへ戻る
          </Link>
        </div>
      </div>
    </div>
  );
}
