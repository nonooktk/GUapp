import Link from "next/link";
import AdminStatusPanel from "@/components/admin/AdminStatusPanel";
import Price from "@/components/Price";
import { ADMIN_RECEIVE_METHOD_LABELS, type AdminOrderDetail as OrderDetail } from "@/lib/admin-types";
import { formatJst } from "@/lib/datetime";
import { formatYen } from "@/lib/format";

/**
 * 注文詳細 DS-SCR-015-4（設計仕様書 P2 追補c 6.5・DS-DEC-118、テスト UT-WEB-47・ST-SEC-87・AT-33・AT-34）。
 * - 顧客が入力した値（氏名・住所・店舗名・追跡番号）は React の既定のエスケープで表示する（dangerouslySetInnerHTML を使わない）
 * - 電話は `phone_masked`（末尾 4 桁以外は `*`）、メールは `email_masked`。**受け取りコードは API が返さず、画面にも出さない**
 * - 郵便番号・住所は配送のときだけ、店舗名・住所は店舗受け取りのときだけ（API の項目が無ければ出さない）
 * - 「次の操作」は `available_transitions` だけで描画する（AdminStatusPanel。画面側に遷移表を置かない）
 */

const section = "space-y-2 rounded-sm border border-line p-4";
const h2 = "text-base font-bold tracking-heading";

function Row({ label, children, testId }: { label: string; children: React.ReactNode; testId?: string }) {
  return (
    <div className="flex flex-wrap gap-x-4 text-sm">
      <dt className="w-32 shrink-0 text-fg-muted">{label}</dt>
      <dd className="min-w-0 break-words" data-testid={testId}>
        {children}
      </dd>
    </div>
  );
}

export default function AdminOrderDetail({ order }: { order: OrderDetail }) {
  const isStore = order.receive_method === "store";
  const c = order.customer;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-light tracking-heading" data-testid="admin-order-number">
          {order.order_number}
        </h1>
        <Link href="/admin/orders" className="inline-flex h-9 items-center text-sm underline underline-offset-2">
          一覧へ戻る
        </Link>
      </div>

      <section aria-labelledby="order-status-heading" className={section}>
        <h2 id="order-status-heading" className={h2}>
          状態
        </h2>
        <dl className="space-y-1">
          <Row label="注文日時（JST）">{formatJst(order.ordered_at)}</Row>
          <Row label="受け取り方法">{ADMIN_RECEIVE_METHOD_LABELS[order.receive_method] ?? order.receive_method}</Row>
        </dl>
        <AdminStatusPanel
          key={`${order.status}:${order.tracking_number ?? ""}`}
          orderNumber={order.order_number}
          status={order.status}
          statusLabel={order.status_label}
          trackingNumber={order.tracking_number}
          transitions={order.available_transitions}
        />
      </section>

      <section aria-labelledby="order-items-heading" className={section}>
        <h2 id="order-items-heading" className={h2}>
          明細
        </h2>
        <ul className="divide-y divide-line text-sm">
          {order.items.map((it, i) => (
            <li key={`${it.product_name}-${it.color}-${it.size}-${i}`} className="flex flex-wrap items-baseline justify-between gap-2 py-2" data-testid="admin-order-item">
              <span>
                {it.product_name}
                <span className="ml-2 text-fg-muted">
                  {it.color} / {it.size}
                </span>
              </span>
              <span className="tabular-nums">
                {formatYen(it.unit_price)} × {it.quantity}
              </span>
            </li>
          ))}
        </ul>
        <dl className="space-y-1 border-t border-line pt-2 text-sm">
          <Row label="小計">
            <Price amount={order.subtotal} />
          </Row>
          <Row label="送料">
            <Price amount={order.shipping_fee} />
          </Row>
          <Row label="値引き">
            <Price amount={order.discount} />
          </Row>
          <Row label="合計">
            <Price amount={order.total} className="font-bold" />
          </Row>
          <Row label="うち消費税">
            <Price amount={order.tax_included} />
          </Row>
        </dl>
      </section>

      <section aria-labelledby="order-customer-heading" className={section}>
        <h2 id="order-customer-heading" className={h2}>
          お客様
        </h2>
        <dl className="space-y-1">
          <Row label="種別">{c.type === "member" ? "会員" : "ゲスト"}</Row>
          <Row label="氏名" testId="admin-customer-name">
            {c.name}
          </Row>
          <Row label="電話（末尾 4 桁）" testId="admin-customer-phone">
            {c.phone_masked}
          </Row>
          <Row label="連絡先メール（マスク）" testId="admin-customer-email">
            {c.email_masked}
          </Row>
          {!isStore && c.postal_code !== undefined && <Row label="お届け先 〒">{c.postal_code}</Row>}
          {!isStore && c.address !== undefined && <Row label="お届け先 住所">{c.address}</Row>}
          {isStore && order.store && (
            <>
              <Row label="受け取り店舗">{order.store.name}</Row>
              <Row label="店舗の住所">{`${order.store.prefecture} ${order.store.address}`}</Row>
            </>
          )}
        </dl>
      </section>

      <section aria-labelledby="order-payment-heading" className={section}>
        <h2 id="order-payment-heading" className={h2}>
          支払い・配送
        </h2>
        <dl className="space-y-1">
          <Row label="支払い方法">{order.payment ? order.payment.provider : "—"}</Row>
          <Row label="支払い結果">{order.payment ? order.payment.result : "—"}</Row>
          {!isStore && order.tracking_number && (
            <Row label="追跡番号" testId="admin-tracking-number">
              {order.tracking_number}
            </Row>
          )}
        </dl>
      </section>
    </div>
  );
}
