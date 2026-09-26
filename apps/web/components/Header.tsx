"use client";

import Link from "next/link";
import { useId, useRef, useState } from "react";
import AllMenu from "@/components/AllMenu";
import SearchBox from "@/components/SearchBox";
import SearchPanel from "@/components/SearchPanel";
import type { Category } from "@/lib/types";

/**
 * 共通ヘッダー（設計仕様書 6.2・U-04・REQ-FR-1201、デザイン基準 v1 3 章「ヘッダー」、
 * P2 追補a 6.1「ヘッダーの検索欄」）。
 * 左: ≡ メニュー ／ 中央: GU ロゴ（テキスト。ロゴ画像は使わない） ／ 右: 検索・お気に入り・カート（点数バッジ）・会員。
 * 高さ 64px、右側は 44×44px のアイコンボタン 4 つ（タッチターゲット最小 44px）。375px 幅でも 1 行に収まる。
 * `sticky top-0` は GU 実サイトと異なる意図的な差（基準 7 章）。
 * 「≡ メニュー」はオールメニューのドロワー（AllMenu・U-06・AT-07）を開閉する。閉じたらフォーカスを「≡」へ戻す。
 * 検索: sm 以上は幅 240px 程度の入力欄を常設（`SearchBox`）。375px は検索アイコンをタップすると
 * オーバーレイの検索パネル（`SearchPanel`）が開く。閉じたら検索アイコンへフォーカスを戻す（AllMenu と同じ規則）。
 * お気に入り・会員の遷移先は P2 以降。
 */

export interface HeaderProps {
  /** カートの点数。0 のときはバッジを表示しない */
  cartCount: number;
  /** オールメニューに出すカテゴリ階層（GET /categories）。取得失敗時は null */
  categories?: Category[] | null;
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

const iconLinkClass = "inline-flex size-11 items-center justify-center rounded-pill text-fg hover:bg-line";

export default function Header({ cartCount, categories = null }: HeaderProps) {
  const badgeLabel = cartCount > 99 ? "99+" : String(cartCount);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const searchPanelId = useId();
  const searchButtonRef = useRef<HTMLButtonElement>(null);

  // 閉じたら「≡」へフォーカスを戻す（デザイン基準 6 章: キーボード操作の連続性）
  const closeMenu = () => {
    setMenuOpen(false);
    menuButtonRef.current?.focus();
  };

  // 閉じたら検索アイコンへフォーカスを戻す（AllMenu と同じ規則。設計仕様書 P2 追補a 6.1）
  const closeSearch = () => {
    setSearchOpen(false);
    searchButtonRef.current?.focus();
  };

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-bg">
      <div className="mx-auto flex h-16 max-w-page items-center justify-between gap-2 px-3 sm:px-4">
        {/* 左: オールメニュー（U-06） */}
        <button
          ref={menuButtonRef}
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          className="inline-flex h-11 min-w-11 items-center justify-center gap-1 rounded-pill px-2 text-sm text-fg hover:bg-line sm:px-3"
          aria-label="メニューを開く"
          aria-haspopup="dialog"
          aria-expanded={menuOpen}
          aria-controls={menuId}
        >
          <span aria-hidden="true" className="text-xl leading-none">
            ≡
          </span>
          <span className="hidden sm:inline">メニュー</span>
        </button>

        {/* 中央: ロゴ（テキスト）＋sm 以上は検索欄をひとまとめにして、menu / このグループ / nav の
            3 グループを justify-between で配置する（P2 追補a 6.1 のワイヤーどおり、ロゴのすぐ右に検索欄）。
            375px は検索欄が無い（hidden）ため、実質ロゴ 1 個の従来どおりの flex 中央寄せになる */}
        <div className="flex shrink-0 items-center gap-3">
          <Link
            href="/"
            className="inline-flex h-11 shrink-0 items-center px-2 text-2xl font-bold tracking-heading text-fg"
            aria-label="GU ホーム"
          >
            GU
          </Link>
          {/* sm 以上の常設検索欄（幅 240px 程度。P2 追補a 6.1） */}
          <SearchBox className="hidden w-60 sm:block" />
        </div>

        {/* 右: 検索（375px のみアイコン）・お気に入り・カート・会員 */}
        <nav aria-label="ユーティリティ" className="flex items-center">
          <button
            ref={searchButtonRef}
            type="button"
            onClick={() => setSearchOpen(true)}
            className={`${iconLinkClass} sm:hidden`}
            aria-label="検索"
            aria-haspopup="dialog"
            aria-expanded={searchOpen}
            aria-controls={searchPanelId}
          >
            <SearchIcon />
          </button>
          <Link href="#" className={iconLinkClass} aria-label="お気に入り">
            <HeartIcon />
          </Link>
          <Link href="/cart" className={`${iconLinkClass} relative`} aria-label={`カート（${cartCount}点）`}>
            <CartIcon />
            {cartCount > 0 && (
              <span
                data-testid="cart-count-badge"
                className="absolute right-0 top-0 inline-flex min-w-5 items-center justify-center rounded-pill bg-accent px-1 text-xs font-bold leading-5 text-primary-fg"
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
      <AllMenu id={menuId} open={menuOpen} categories={categories} onClose={closeMenu} />
      <SearchPanel id={searchPanelId} open={searchOpen} onClose={closeSearch} />
    </header>
  );
}
