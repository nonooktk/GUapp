import Link from "next/link";

/**
 * パンくず（デザイン基準 v1 3 章「パンくず」）。商品一覧・商品詳細で使う。
 * `--text-sm`・`--color-fg-muted`、区切りは「>」。最後の項目（現在地）は `aria-current="page"` で文字色を --color-fg にする。
 * `href` の無い項目はテキストのみ。
 */

export interface Crumb {
  label: string;
  href?: string;
}

export default function Breadcrumb({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="パンくず" className="text-sm text-fg-muted">
      <ol className="flex flex-wrap items-center gap-2">
        {items.map((item, i) => {
          const last = i === items.length - 1;
          return (
            <li key={`${item.label}-${i}`} className="flex min-w-0 items-center gap-2">
              {i > 0 && <span aria-hidden="true">&gt;</span>}
              {item.href && !last ? (
                <Link href={item.href} className="hover:underline">
                  {item.label}
                </Link>
              ) : (
                <span aria-current={last ? "page" : undefined} className={last ? "truncate text-fg" : undefined}>
                  {item.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
