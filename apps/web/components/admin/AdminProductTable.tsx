import Link from "next/link";
import Price from "@/components/Price";
import type { AdminProductListItem } from "@/lib/admin-types";

/**
 * 商品一覧の表（設計仕様書 P2 追補c 6.4・DS-SCR-015-1）。Server Component から使える（フックなし）。
 * - 在庫 0 の SKU がある行は「在庫0のSKU数」を強調する。非公開の行は「非公開」のバッジを灰色にする
 * - 商品名は React の既定のエスケープで表示する（dangerouslySetInnerHTML を使わない）
 * - 375px では表の枠の中だけ横にスクロールし、ページ全体の横スクロールを出さない
 */

export default function AdminProductTable({ items }: { items: AdminProductListItem[] }) {
  if (items.length === 0) {
    return (
      <p className="rounded-sm border border-line p-6 text-center text-sm text-fg-muted" data-testid="admin-products-empty">
        条件に合う商品はありません
      </p>
    );
  }
  return (
    <div className="relative overflow-x-auto rounded-sm border border-line">
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <caption className="sr-only">商品一覧</caption>
        <thead className="bg-line/40 text-left">
          <tr>
            <th scope="col" className="px-3 py-2">ID</th>
            <th scope="col" className="px-3 py-2">商品名</th>
            <th scope="col" className="px-3 py-2 text-right">価格</th>
            <th scope="col" className="px-3 py-2">公開</th>
            <th scope="col" className="px-3 py-2 text-right">在庫計</th>
            <th scope="col" className="px-3 py-2 text-right">在庫0のSKU数</th>
            <th scope="col" className="px-3 py-2">
              <span className="sr-only">操作</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((p) => (
            <tr key={p.product_id} className="border-t border-line" data-testid="admin-product-row">
              <td className="px-3 py-2 tabular-nums">{p.product_id}</td>
              <td className="px-3 py-2">{p.name}</td>
              <td className="px-3 py-2 text-right">
                <Price amount={p.price_incl_tax} />
              </td>
              <td className="px-3 py-2">
                {p.published ? (
                  <span className="inline-block rounded-pill border border-fg px-2 text-xs">公開</span>
                ) : (
                  <span className="inline-block rounded-pill bg-disabled-bg px-2 text-xs text-fg-muted" data-testid="admin-private-badge">
                    非公開
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{p.total_stock}</td>
              <td className={`px-3 py-2 text-right tabular-nums ${p.out_of_stock_variants > 0 ? "font-bold text-danger" : ""}`} data-testid="admin-out-of-stock">
                {p.out_of_stock_variants}
              </td>
              <td className="px-3 py-2 text-right">
                <Link href={`/admin/products/${p.product_id}`} className="inline-flex h-8 items-center underline underline-offset-2" aria-label={`${p.name}を編集`}>
                  編集
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
