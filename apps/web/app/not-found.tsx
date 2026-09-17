import Link from "next/link";

/** 404（存在しない・非公開商品など。設計仕様書 4.5: 3 者を区別しない） */
export default function NotFound() {
  return (
    <div className="py-16 text-center">
      <h1 className="text-xl font-bold">ページが見つかりません</h1>
      <p className="mt-2 text-sm text-gray-700">URL が間違っているか、商品が取り扱い終了になった可能性があります。</p>
      <Link
        href="/"
        className="mt-6 inline-flex h-11 items-center rounded-md border border-gray-900 px-6 text-sm font-bold hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
      >
        ホームへ戻る
      </Link>
    </div>
  );
}
