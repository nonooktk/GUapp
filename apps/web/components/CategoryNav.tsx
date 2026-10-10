import Link from "next/link";
import { GENDERS } from "@/lib/gender";
import type { Category } from "@/lib/types";

/**
 * 商品一覧のカテゴリ導線（設計仕様書 6.4・AT-07）。上部に性別タブ、その下に子カテゴリを横スクロールで並べる。
 * タブはピル形（デザイン基準 v1 2.3）・高さ 44px。選択中は --color-primary 背景。
 * `categories` は DS-API-001 の応答。取得に失敗したときは性別タブだけ出す。
 *
 * - 性別を選んでいるとき: その性別の子カテゴリを 1 枚ずつ並べる。リンクは `?gender=&category=<slug>`、選択中は URL の category
 * - ALL（性別なし）のとき: 3 性別の同じ種類（kind）を 1 枚にまとめる。表示名は最初に出てきた名前、件数は合計、
 *   並びは最初に出てきた順。リンクは `?kind=<kind>`、選択中は URL の kind。
 *   カテゴリは性別ごとに別の行（women-tops・men-tops …）なので、slug で絞ると 1 性別だけになってしまうため。
 */

export interface CategoryNavProps {
  categories: Category[] | null;
  gender?: string;
  category?: string;
  /** ALL のときの選択中の種類（URL の kind） */
  kind?: string;
}

interface NavItem {
  key: string;
  name: string;
  count: number;
  href: string;
  on: boolean;
}

const tabBase = "inline-flex h-11 shrink-0 items-center rounded-pill border px-4 text-sm";
const tabOn = "border-primary bg-primary text-primary-fg";
const tabOff = "border-line bg-bg text-fg hover:bg-line";

/** ALL 用: 子カテゴリを kind ごとに 1 枚へまとめる（kind が無い子は束ねず slug で 1 枚ずつ） */
function groupByKind(categories: Category[], kind?: string): NavItem[] {
  const groups = new Map<string, NavItem>();
  for (const parent of categories) {
    for (const child of parent.children) {
      const key = child.kind ?? `slug:${child.slug}`;
      const found = groups.get(key);
      if (found) {
        found.count += child.product_count;
        continue;
      }
      groups.set(key, {
        key,
        name: child.name,
        count: child.product_count,
        href: child.kind
          ? `/products?${new URLSearchParams({ kind: child.kind }).toString()}`
          : `/products?${new URLSearchParams({ category: child.slug }).toString()}`,
        on: child.kind !== null && child.kind === kind,
      });
    }
  }
  return [...groups.values()];
}

/** 性別を選んでいるとき用: その性別（と共通 all）の子カテゴリを slug ごとに 1 枚ずつ */
function listByGender(categories: Category[], gender: string, category?: string): NavItem[] {
  return categories
    .filter((c) => c.gender === gender || c.gender === "all")
    .flatMap((c) =>
      c.children.map((child) => ({
        // 親（性別）slug を key に含める（同名・同 slug の子が別の親に並びうるため）
        key: `${c.slug}/${child.slug}`,
        name: child.name,
        count: child.product_count,
        href: `/products?${new URLSearchParams({ gender, category: child.slug }).toString()}`,
        on: category === child.slug,
      })),
    );
}

export default function CategoryNav({ categories, gender, category, kind }: CategoryNavProps) {
  const items: NavItem[] = !categories ? [] : gender ? listByGender(categories, gender, category) : groupByKind(categories, kind);

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
      {items.length > 0 && (
        <ul className="flex gap-2 overflow-x-auto pb-1" aria-label="商品カテゴリ">
          {items.map((c) => (
            <li key={c.key} className="shrink-0">
              <Link
                href={c.href}
                className={`${tabBase} whitespace-nowrap ${c.on ? tabOn : tabOff}`}
                aria-current={c.on ? "page" : undefined}
              >
                {c.name}
                <span className={`ml-1 text-xs ${c.on ? "text-primary-fg/80" : "text-fg-muted"}`}>{c.count}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );
}
