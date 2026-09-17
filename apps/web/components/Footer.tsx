import Link from "next/link";

/**
 * 共通フッター（設計仕様書 6.2・U-04）。5 リンク。遷移先は P2 で実装するため `#`。
 */

const FOOTER_LINKS = [
  { label: "企業情報", href: "#" },
  { label: "利用規約", href: "#" },
  { label: "プライバシー", href: "#" },
  { label: "特商法", href: "#" },
  { label: "FAQ", href: "#" },
] as const;

export default function Footer() {
  return (
    <footer className="mt-auto border-t border-gray-200 bg-gray-50">
      <nav aria-label="フッター" className="mx-auto max-w-screen-xl px-4 py-6">
        <ul className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-sm text-gray-700">
          {FOOTER_LINKS.map((link) => (
            <li key={link.label}>
              <Link
                href={link.href}
                className="inline-block py-1 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
              >
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-center text-xs text-gray-500">GU EC サイト（演習用・P1）</p>
      </nav>
    </footer>
  );
}
