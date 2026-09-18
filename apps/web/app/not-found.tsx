import Link from "next/link";
import { buttonClass } from "@/components/Button";

/** 404（存在しない・非公開商品など。設計仕様書 4.5: 3 者を区別しない） */
export default function NotFound() {
  return (
    <div className="py-16 text-center">
      <h1 className="text-xl font-light tracking-heading">ページが見つかりません</h1>
      <p className="mt-2 text-sm text-fg-muted">URL が間違っているか、商品が取り扱い終了になった可能性があります。</p>
      <Link href="/" className={buttonClass({ variant: "secondary", size: "lg", className: "mt-6" })}>
        ホームへ戻る
      </Link>
    </div>
  );
}
