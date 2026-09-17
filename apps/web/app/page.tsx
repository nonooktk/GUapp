import Link from "next/link";

/**
 * ホーム DS-SCR-001（設計仕様書 6.3）の仮置き。
 * Wave 0: 性別 3 区分のリンクとプレースホルダーのみ。トップ画像・おすすめ商品（DS-API-001/002）は Wave 1。
 */

const GENDER_LINKS = [
  { label: "WOMEN", gender: "women" },
  { label: "MEN", gender: "men" },
  { label: "KIDS・TEEN", gender: "kids" },
] as const;

export default function HomePage() {
  return (
    <div className="space-y-8">
      {/* トップ画像（U-01）: Wave 1 で差し替え */}
      <section
        aria-label="特集"
        className="flex h-48 items-center justify-center rounded-lg bg-gray-100 text-sm text-gray-500 sm:h-72"
      >
        トップ画像（Wave 1 で実装）
      </section>

      {/* カテゴリ（U-02） */}
      <section aria-labelledby="category-heading">
        <h2 id="category-heading" className="mb-3 text-lg font-bold">
          カテゴリ
        </h2>
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {GENDER_LINKS.map((item) => (
            <li key={item.gender}>
              <Link
                href={`/products?gender=${item.gender}`}
                className="flex h-24 items-center justify-center rounded-lg border border-gray-300 bg-white text-base font-bold hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {/* おすすめ商品（U-03）: Wave 1 で DS-API-001 から取得 */}
      <section aria-labelledby="recommend-heading">
        <h2 id="recommend-heading" className="mb-3 text-lg font-bold">
          おすすめ商品
        </h2>
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="おすすめ商品（準備中）">
          {Array.from({ length: 4 }, (_, i) => (
            <li key={i} className="aspect-[3/4] rounded-lg bg-gray-100" aria-hidden="true" />
          ))}
        </ul>
        <p className="mt-2 text-sm text-gray-500">商品データは Wave 1 で表示します。</p>
      </section>
    </div>
  );
}
