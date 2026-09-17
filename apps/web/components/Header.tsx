import Link from "next/link";

/**
 * 共通ヘッダー（設計仕様書 6.2・U-04・REQ-FR-1201）。
 * 左: ≡ メニュー ／ 中央: GU ロゴ（テキスト） ／ 右: 検索・お気に入り・カート（点数バッジ）・会員。
 * 375px 幅でも 1 行に収まるよう、右側は 40px 角のアイコンボタン 4 つに固定する。
 * オールメニューの中身（U-06）と各リンク先は Wave 1 以降で実装する。
 */

export interface HeaderProps {
  /** カートの点数。0 のときはバッジを表示しない */
  cartCount: number;
}

const iconClass = "size-6";

function SearchIcon() {
  return (
    <svg className={iconClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" strokeLinecap="round" />
    </svg>
  );
}

function HeartIcon() {
  return (
    <svg className={iconClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path
        d="M12 20.5s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.9a4.3 4.3 0 0 1 7.5 2.6c0 5.4-7.5 10-7.5 10Z"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CartIcon() {
  return (
    <svg className={iconClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M3 4h2l2.5 11h11L21 7H6.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="9" cy="19" r="1.5" />
      <circle cx="17" cy="19" r="1.5" />
    </svg>
  );
}

function UserIcon() {
  return (
    <svg className={iconClass} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="12" cy="8.5" r="4" />
      <path d="M4.5 20a7.5 7.5 0 0 1 15 0" strokeLinecap="round" />
    </svg>
  );
}

const iconLinkClass =
  "inline-flex size-10 items-center justify-center rounded-md text-gray-800 hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900";

export default function Header({ cartCount }: HeaderProps) {
  const badgeLabel = cartCount > 99 ? "99+" : String(cartCount);
  return (
    <header className="sticky top-0 z-40 border-b border-gray-200 bg-white">
      <div className="mx-auto flex h-14 max-w-screen-xl items-center justify-between gap-2 px-3 sm:px-4">
        {/* 左: オールメニュー（U-06。中身は Wave 1 以降） */}
        <button
          type="button"
          className="inline-flex h-10 items-center gap-1 rounded-md px-2 text-sm font-medium text-gray-800 hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
          aria-label="メニューを開く"
          aria-haspopup="dialog"
          aria-expanded={false}
        >
          <span aria-hidden="true" className="text-xl leading-none">
            ≡
          </span>
          <span className="hidden sm:inline">メニュー</span>
        </button>

        {/* 中央: ロゴ（テキスト） */}
        <Link
          href="/"
          className="absolute left-1/2 -translate-x-1/2 text-2xl font-black tracking-tight text-gray-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
          aria-label="GU ホーム"
        >
          GU
        </Link>

        {/* 右: 検索・お気に入り・カート・会員 */}
        <nav aria-label="ユーティリティ" className="flex items-center">
          <Link href="#" className={iconLinkClass} aria-label="検索">
            <SearchIcon />
          </Link>
          <Link href="#" className={iconLinkClass} aria-label="お気に入り">
            <HeartIcon />
          </Link>
          <Link href="/cart" className={`${iconLinkClass} relative`} aria-label={`カート（${cartCount}点）`}>
            <CartIcon />
            {cartCount > 0 && (
              <span
                data-testid="cart-count-badge"
                className="absolute -right-0.5 -top-0.5 inline-flex min-w-5 items-center justify-center rounded-full bg-red-600 px-1 text-xs font-bold leading-5 text-white"
                aria-hidden="true"
              >
                {badgeLabel}
              </span>
            )}
          </Link>
          <Link href="#" className={iconLinkClass} aria-label="会員">
            <UserIcon />
          </Link>
        </nav>
      </div>
    </header>
  );
}
