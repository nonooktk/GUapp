import Price from "@/components/Price";
import { formatNumber } from "@/lib/format";
import type { OrderItem } from "@/lib/types";

/**
 * 注文確認・完了（DS-SCR-006）で共用する表示部品（デザイン基準 v1 4 章 SCR-006）。
 * - OrderItemsList: 明細（名称・色/サイズ・単価・数量・小計）。カートと同じ行構成。画像は任意（完了画面の応答には無い）
 * - AmountSummary: 小計・送料・合計・うち消費税を縦積みの dl（カートの金額サマリと同じスタイル）
 * - ShippingSummary: お届け先・メール・受け取り方法・支払い方法
 */

export interface OrderItemLike extends OrderItem {
  variant_id?: number;
  image_url?: string | null;
}

export function OrderItemsList({ items, label = "注文内容" }: { items: OrderItemLike[]; label?: string }) {
  return (
    <ul className="divide-y divide-line" aria-label={label}>
      {items.map((item, i) => (
        <li key={`${item.variant_id ?? i}-${item.color}-${item.size}`} className="flex gap-3 py-4" data-testid="order-item">
          {item.image_url !== undefined && (
            // eslint-disable-next-line @next/next/no-img-element -- プレースホルダー PNG を素直に表示
            <img src={item.image_url ?? undefined} alt="" className="aspect-[3/4] w-20 shrink-0 rounded-sm bg-line/50 object-cover" />
          )}
          <div className="min-w-0 flex-1 text-sm">
            <p className="text-base font-light">{item.product_name}</p>
            <p className="mt-0.5 text-fg-muted">
              {item.color} / {item.size}
            </p>
            <div className="mt-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <p>
                単価 <Price amount={item.unit_price} /> × {item.quantity}
              </p>
              <p className="text-lg font-bold tracking-heading">
                <span className="text-sm font-normal tracking-normal">小計 </span>
                <Price amount={item.line_total} />
              </p>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

export interface AmountSummaryProps {
  subtotal: number;
  shipping_fee: number;
  total: number;
  tax_included: number;
  free_shipping_threshold?: number;
  /** aside の見出し */
  label?: string;
}

export function AmountSummary({ subtotal, shipping_fee, total, tax_included, free_shipping_threshold, label = "金額" }: AmountSummaryProps) {
  return (
    <aside className="h-fit rounded-sm border border-line bg-line/40 p-4 text-sm" aria-label={label} data-testid="amount-summary">
      <dl className="space-y-2">
        <div className="flex justify-between">
          <dt>小計</dt>
          <dd>
            <Price amount={subtotal} />
          </dd>
        </div>
        <div className="flex justify-between">
          <dt>
            送料
            {free_shipping_threshold !== undefined && (
              <span className="ml-1 text-xs text-fg-muted">（{formatNumber(free_shipping_threshold)} 円以上で無料）</span>
            )}
          </dt>
          <dd>{shipping_fee === 0 ? "無料" : <Price amount={shipping_fee} />}</dd>
        </div>
        <div className="flex items-baseline justify-between border-t border-line pt-3 text-base font-bold">
          <dt>合計</dt>
          <dd>
            <Price amount={total} taxNote className="text-lg tracking-heading" />
          </dd>
        </div>
        <div className="flex justify-between text-xs text-fg-muted">
          <dt>うち消費税</dt>
          <dd>
            <Price amount={tax_included} />
          </dd>
        </div>
      </dl>
    </aside>
  );
}

export interface ShippingSummaryProps {
  ship_name: string;
  ship_postal_code: string;
  ship_address: string;
  ship_phone: string;
  guest_email: string;
  receive_method: string;
  payment_method: string;
}

/** 郵便番号 7 桁を `100-0001` の形に、電話を読みやすく区切る（表示だけ。送信値は数字のみ） */
export function formatPostal(digits: string): string {
  return /^[0-9]{7}$/.test(digits) ? `${digits.slice(0, 3)}-${digits.slice(3)}` : digits;
}

export function receiveMethodLabel(v: string): string {
  return v === "delivery" ? "配送" : v === "store" ? "店舗受け取り" : v;
}

export function paymentMethodLabel(v: string): string {
  return v === "card" ? "クレジットカード（テスト決済）" : v;
}

export function ShippingSummary(p: ShippingSummaryProps) {
  const row = "grid gap-1 sm:grid-cols-[8rem_1fr]";
  const dt = "text-fg-muted";
  return (
    <dl className="space-y-3 text-sm" data-testid="shipping-summary">
      <div className={row}>
        <dt className={dt}>お届け先</dt>
        <dd>
          <p>{p.ship_name} 様</p>
          <p>〒{formatPostal(p.ship_postal_code)}</p>
          <p className="break-words">{p.ship_address}</p>
          <p>電話 {p.ship_phone}</p>
        </dd>
      </div>
      <div className={row}>
        <dt className={dt}>メールアドレス</dt>
        <dd className="break-all">{p.guest_email}</dd>
      </div>
      <div className={row}>
        <dt className={dt}>受け取り方法</dt>
        <dd>{receiveMethodLabel(p.receive_method)}</dd>
      </div>
      <div className={row}>
        <dt className={dt}>支払い方法</dt>
        <dd>{paymentMethodLabel(p.payment_method)}</dd>
      </div>
    </dl>
  );
}
