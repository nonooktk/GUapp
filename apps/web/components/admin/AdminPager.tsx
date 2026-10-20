import Link from "next/link";
import { buildListHref } from "@/lib/admin-query";

/**
 * 管理画面の一覧のページ送り（設計仕様書 P2 追補c 6.4・6.5、テスト UT-WEB-54）。Server Component から使える（フックなし）。
 * - 「全 N 件」を常に出す。総件数 0 は「該当なし」
 * - 前後のリンクは 2 ページ以上あるときだけ出す。先頭は「前へ」なし、最後（`hasMore` が偽）は「次へ」なし
 * - リンクの `page` は 1 以上の整数。他の検索条件（`linkParams`）を保つ。1 ページ目のリンクは `page` を付けない
 */

export interface AdminPagerProps {
  basePath: string;
  linkParams: Record<string, string>;
  page: number;
  perPage: number;
  total: number;
  hasMore: boolean;
}

const linkClass = "inline-flex h-9 min-w-9 items-center justify-center rounded-sm border border-line px-3 text-sm hover:bg-line";

/** 現在のページの前後 2 ページずつ（最大 5 つ）を、1 から最終ページの範囲で返す */
function pageWindow(page: number, totalPages: number): number[] {
  const start = Math.max(1, page - 2);
  const end = Math.min(totalPages, page + 2);
  const out: number[] = [];
  for (let p = start; p <= end; p++) out.push(p);
  return out;
}

export default function AdminPager({ basePath, linkParams, page, perPage, total, hasMore }: AdminPagerProps) {
  if (total <= 0) {
    return (
      <p className="text-sm text-fg-muted" data-testid="admin-pager-count">
        該当なし
      </p>
    );
  }
  const safePage = Number.isInteger(page) && page >= 1 ? page : 1;
  const totalPages = Math.max(1, Math.ceil(total / Math.max(1, perPage)));
  const showNav = totalPages > 1 || hasMore || safePage > 1;
  const href = (p: number) => buildListHref(basePath, linkParams, p);

  return (
    <div className="flex flex-wrap items-center gap-4">
      <p className="text-sm text-fg-muted" data-testid="admin-pager-count">
        全 {total.toLocaleString("ja-JP")} 件
      </p>
      {showNav && (
        <nav aria-label="ページ送り" className="flex flex-wrap items-center gap-1">
          {safePage > 1 && (
            <Link href={href(safePage - 1)} rel="prev" className={linkClass}>
              « 前へ
            </Link>
          )}
          {pageWindow(safePage, totalPages).map((p) =>
            p === safePage ? (
              <span key={p} aria-current="page" className="inline-flex h-9 min-w-9 items-center justify-center rounded-sm bg-primary px-3 text-sm font-bold text-primary-fg">
                {p}
              </span>
            ) : (
              <Link key={p} href={href(p)} className={linkClass}>
                {p}
              </Link>
            ),
          )}
          {hasMore && (
            <Link href={href(safePage + 1)} rel="next" className={linkClass}>
              次へ »
            </Link>
          )}
        </nav>
      )}
    </div>
  );
}
