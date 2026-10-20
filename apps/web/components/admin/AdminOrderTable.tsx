import Link from "next/link";
import Price from "@/components/Price";
import { ADMIN_RECEIVE_METHOD_LABELS, type AdminOrderListItem } from "@/lib/admin-types";
import { formatJst } from "@/lib/datetime";

/**
 * 注文一覧の表（設計仕様書 P2 追補c 6.5・DS-SCR-015-3、テスト AT-33）。Server Component から使える（フックなし）。
 * - 連絡先は `email_masked`（`t***@example.com`）だけ。氏名・電話・住所は一覧に出さない（API も返さない。DS-DEC-118）
 * - 行を押すと詳細へ移る（注文番号のリンクを行全体に広げる）。日時は JST（`YYYY/MM/DD HH:mm`）
 * - 375px では表の枠の中だけ横にスクロールする
 */

export default function AdminOrderTable({ items }: { items: AdminOrderListItem[] }) {
  if (items.length === 0) {
    return (
      <p className="rounded-sm border border-line p-6 text-center text-sm text-fg-muted" data-testid="admin-orders-empty">
        条件に合う注文はありません
      </p>
    );
  }
  return (
    <div className="relative overflow-x-auto rounded-sm border border-line">
      <table className="w-full min-w-[820px] border-collapse text-sm">
        <caption className="sr-only">注文一覧</caption>
        <thead className="bg-line/40 text-left">
          <tr>
            <th scope="col" className="px-3 py-2">注文番号</th>
            <th scope="col" className="px-3 py-2">注文日時（JST）</th>
            <th scope="col" className="px-3 py-2">状態</th>
            <th scope="col" className="px-3 py-2">受取</th>
            <th scope="col" className="px-3 py-2 text-right">合計</th>
            <th scope="col" className="px-3 py-2 text-right">点数</th>
            <th scope="col" className="px-3 py-2">連絡先</th>
          </tr>
        </thead>
        <tbody>
          {items.map((o) => (
            <tr key={o.order_number} className="relative border-t border-line hover:bg-line/40" data-testid="admin-order-row">
              <td className="px-3 py-2">
                <Link
                  href={`/admin/orders/${encodeURIComponent(o.order_number)}`}
                  className="font-bold underline underline-offset-2 after:absolute after:inset-0 after:content-['']"
                >
                  {o.order_number}
                </Link>
              </td>
              <td className="px-3 py-2 tabular-nums">{formatJst(o.ordered_at)}</td>
              <td className="px-3 py-2">{o.status_label}</td>
              <td className="px-3 py-2">{ADMIN_RECEIVE_METHOD_LABELS[o.receive_method] ?? o.receive_method}</td>
              <td className="px-3 py-2 text-right">
                <Price amount={o.total} />
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{o.item_count}</td>
              <td className="px-3 py-2">
                <span>{o.email_masked}</span>
                <span className="ml-2 text-xs text-fg-muted">{o.customer_type === "member" ? "会員" : "ゲスト"}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
