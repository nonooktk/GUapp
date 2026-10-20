import Link from "next/link";
import { buttonClass } from "@/components/Button";
import Price from "@/components/Price";
import { formatJst } from "@/lib/datetime";
import type { OrderHistoryResponse } from "@/lib/types";

/**
 * 注文履歴の一覧 DS-SCR-008（設計仕様書 6.4・DS-API-024、テスト UT-WEB-22・AT-14）。
 * - 見出し「ご注文履歴（全 N 件）」。1 件ごとに注文日（JST）・注文番号・`status_label`・先頭の商品名と「ほか N 点」（N = item_count - 1。1 点のときは付けない）・
 *   受け取り方法・合計。カード全体が詳細（DS-SCR-009）へのリンク（タッチターゲット 44px 以上）
 * - 0 件: 「まだご注文がありません」とホームへのリンク。範囲外のページ: 「このページには注文がありません」と 1 ページ目へのリンク
 * - ページング: `?page=N`（10 件ずつ）。「前へ」「次へ」は `page` と `has_more` で出し分ける
 * Server Component から描ける（フックなし）。
 */

export function receiveMethodShort(v: string): string {
  return v === "store" ? "店舗受け取り" : v === "delivery" ? "配送" : v;
}

/** 「○○ほか N 点」。item_count が 1 以下なら商品名だけ */
export function firstItemLabel(name: string, itemCount: number): string {
  return itemCount > 1 ? `${name}ほか ${itemCount - 1} 点` : name;
}

export function pageHref(page: number): string {
  return page <= 1 ? "/mypage" : `/mypage?page=${page}`;
}

const pagerLink = buttonClass({ variant: "secondary", size: "md" });

export default function OrderHistoryList({ history }: { history: OrderHistoryResponse }) {
  const { items, page, per_page, total, has_more } = history;

  if (total === 0 && items.length === 0) {
    return (
      <section aria-labelledby="history-heading" className="space-y-3">
        <h2 id="history-heading" className="text-lg font-light tracking-heading">
          ご注文履歴
        </h2>
        <div className="space-y-3 rounded-sm border border-line bg-line/40 p-6 text-center text-sm" data-testid="history-empty">
          <p>まだご注文がありません</p>
          <Link href="/" className={buttonClass({ variant: "secondary", size: "md" })}>
            ホームへ
          </Link>
        </div>
      </section>
    );
  }

  const totalPages = Math.max(1, Math.ceil(total / Math.max(1, per_page)));

  return (
    <section aria-labelledby="history-heading" className="space-y-4">
      <h2 id="history-heading" className="text-lg font-light tracking-heading">
        ご注文履歴（全 {total} 件）
      </h2>

      {items.length === 0 ? (
        <div className="space-y-3 rounded-sm border border-line bg-line/40 p-6 text-center text-sm" data-testid="history-out-of-range">
          <p>このページには注文がありません</p>
          <Link href={pageHref(1)} className={buttonClass({ variant: "secondary", size: "md" })}>
            1 ページ目へ
          </Link>
        </div>
      ) : (
        <ul className="space-y-3" aria-label="注文履歴">
          {items.map((o) => (
            <li key={o.order_number}>
              <Link
                href={`/mypage/orders/${encodeURIComponent(o.order_number)}`}
                className="block min-h-11 rounded-sm border border-line p-4 text-sm hover:bg-line/40"
                data-testid="history-item"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <p className="text-fg-muted">
                    {formatJst(o.ordered_at).slice(0, 10)} <span className="break-all text-fg">{o.order_number}</span>
                  </p>
                  <p className="rounded-pill border border-fg px-3 text-xs font-bold" data-testid="history-status">
                    {o.status_label}
                  </p>
                </div>
                <p className="mt-2 break-words">{firstItemLabel(o.first_item_name, o.item_count)}</p>
                <div className="mt-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <p className="text-fg-muted">{receiveMethodShort(o.receive_method)}</p>
                  <p className="text-lg font-bold tracking-heading">
                    <Price amount={o.total} />
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {(page > 1 || has_more) && (
        <nav aria-label="ページ送り" className="flex items-center justify-between gap-3">
          {page > 1 ? (
            <Link href={pageHref(page - 1)} className={pagerLink} rel="prev">
              前へ
            </Link>
          ) : (
            <span aria-hidden="true" className="w-20" />
          )}
          <p className="text-sm" aria-live="polite">
            {page} / {totalPages}
          </p>
          {has_more ? (
            <Link href={pageHref(page + 1)} className={pagerLink} rel="next">
              次へ
            </Link>
          ) : (
            <span aria-hidden="true" className="w-20" />
          )}
        </nav>
      )}
    </section>
  );
}
