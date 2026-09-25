import Link from "next/link";

/**
 * 共通フッター（設計仕様書 6.2・U-04、デザイン基準 v1 3 章「フッター」）。5 リンク。
 * 遷移先は P2-a（設計仕様書 P2 追補a 6.5）で確定した `/contents/{slug}`。
 * 文字色は --color-fg-muted。リンクは縦 py-3 でタッチターゲット 44px 以上を確保する。
 */

const FOOTER_LINKS = [
  { label: "企業情報", href: "/contents/company" },
  { label: "利用規約", href: "/contents/terms" },
  { label: "プライバシー", href: "/contents/privacy" },
  { label: "特商法", href: "/contents/tokushoho" },
  { label: "FAQ", href: "/contents/faq" },
] as const;

export default function Footer() {
  return (
    <footer className="mt-auto border-t border-line bg-line/30">
      <nav aria-label="フッター" className="mx-auto max-w-page px-4 py-6">
        <ul className="flex flex-wrap items-center justify-center gap-x-3 text-sm text-fg-muted">
          {FOOTER_LINKS.map((link) => (
            <li key={link.label}>
              <Link href={link.href} className="inline-flex min-w-11 items-center justify-center px-1 py-3 hover:underline">
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-center text-xs text-fg-muted">GU EC サイト（演習用・P1）</p>
      </nav>
    </footer>
  );
}
