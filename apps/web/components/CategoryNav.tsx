import Link from "next/link";
import { GENDERS } from "@/lib/gender";
import type { Category } from "@/lib/types";

/**
 * 商品一覧のカテゴリ導線（設計仕様書 6.4・AT-07）。上部に性別タブ、その下に選択中性別の子カテゴリを横スクロールで並べる。
 * タブはピル形（デザイン基準 v1 2.3）・高さ 44px。選択中は --color-primary 背景。
 * `categories` は DS-API-001 の応答。取得に失敗したときは性別タブだけ出す。
 */

export interface CategoryNavProps {
  categories: Category[] | null;
  gender?: string;
  category?: string;
}

const tabBase = "inline-flex h-11 shrink-0 items-center rounded-pill border px-4 text-sm";
const tabOn = "border-primary bg-primary text-primary-fg";
const tabOff = "border-line bg-bg text-fg hover:bg-line";

export default function CategoryNav({ categories, gender, category }: CategoryNavProps) {
  // 親（性別）slug を key に含める。ALL 表示では WOMEN／MEN に同名・同 slug の子が並びうる
  const children =
    categories
      ?.filter((c) => !gender || c.gender === gender || c.gender === "all")
      .flatMap((c) => c.children.map((child) => ({ ...child, parentSlug: c.slug }))) ?? [];

  return (
    <nav aria-label="カテゴリ" className="space-y-2">
      <ul className="flex gap-2 overflow-x-auto pb-1">
        <li className="shrink-0">
          <Link href="/products" className={`${tabBase} ${!gender ? tabOn : tabOff}`} aria-current={!gender ? "page" : undefined}>
            ALL
          </Link>
        </li>
        {GENDERS.map((g) => (
          <li key={g.slug} className="shrink-0">
            <Link
              href={`/products?gender=${g.slug}`}
              className={`${tabBase} ${gender === g.slug ? tabOn : tabOff}`}
              aria-current={gender === g.slug ? "page" : undefined}
            >
              {g.label}
            </Link>
          </li>
        ))}
      </ul>
      {children.length > 0 && (
        <ul className="flex gap-2 overflow-x-auto pb-1" aria-label="商品カテゴリ">
          {children.map((c) => {
            const href = `/products?${new URLSearchParams({ ...(gender ? { gender } : {}), category: c.slug }).toString()}`;
            const on = category === c.slug;
            return (
              <li key={`${c.parentSlug}/${c.slug}`} className="shrink-0">
                <Link
                  href={href}
                  className={`${tabBase} whitespace-nowrap ${on ? tabOn : tabOff}`}
                  aria-current={on ? "page" : undefined}
                >
                  {c.name}
                  <span className={`ml-1 text-xs ${on ? "text-primary-fg/80" : "text-fg-muted"}`}>{c.product_count}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
