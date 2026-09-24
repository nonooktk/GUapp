"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { GENDERS } from "@/lib/gender";
import type { Category } from "@/lib/types";

/**
 * オールメニューのドロワー（設計仕様書 6.2・U-06・AT-07、デザイン基準 v1 3 章「ヘッダー」・6 章）。
 * ヘッダー左の「≡ メニュー」で開閉する。P1 範囲は性別 3 区分（WOMEN／MEN／KIDS・TEEN）と、その下の商品カテゴリ階層だけ。
 * お知らせ・FAQ・INFO は P2 のためテキストリンク（`#`）で置くのみ。
 *
 * - パネル: `role="dialog"`・`aria-modal="true"`・`aria-labelledby`。375px は全幅、sm 以上は 320px（w-80）で左から出す
 * - 開いたら閉じるボタンにフォーカス。Escape・背景クリック・リンク選択で閉じる。Tab はパネル内で循環（ConfirmDialog と同じ方式）
 * - 閉じたあと「≡」へフォーカスを戻すのは親（Header）が行う
 * - `categories` が null（取得失敗）のときは性別リンクだけ出し、「読み込めませんでした」を添える
 */

export interface AllMenuProps {
  /** ドロワーの id。ヘッダーの `aria-controls` と一致させる */
  id: string;
  open: boolean;
  categories: Category[] | null;
  onClose: () => void;
}

const FOCUSABLE = "a[href], button:not([disabled])";

const P2_LINKS = [
  { label: "お知らせ", href: "#" },
  { label: "FAQ", href: "#" },
  { label: "INFO", href: "#" },
] as const;

const rowClass = "flex min-h-11 items-center justify-between px-4 py-2 text-fg hover:bg-line";

export default function AllMenu({ id, open, categories, onClose }: AllMenuProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // 開いたら閉じるボタンへフォーカス。開いている間は背面のスクロールを止める
  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  if (!open) return null;

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === "Tab" && panelRef.current) {
      const focusables = panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  const titleId = `${id}-title`;

  return (
    <div className="fixed inset-0 z-[60] flex bg-overlay" onClick={onClose} data-testid="all-menu-overlay">
      <div
        id={id}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        className="flex h-full w-full flex-col overflow-y-auto bg-bg shadow-modal sm:w-80"
      >
        <div className="flex h-16 shrink-0 items-center justify-between border-b border-line px-4">
          <h2 id={titleId} className="text-lg font-bold tracking-heading text-fg">
            メニュー
          </h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="inline-flex size-11 items-center justify-center rounded-pill text-fg hover:bg-line"
            aria-label="メニューを閉じる"
          >
            <span aria-hidden="true" className="text-xl leading-none">
              ×
            </span>
          </button>
        </div>

        <nav aria-label="オールメニュー" className="flex-1 py-2">
          {GENDERS.map((g) => {
            const parent = categories?.find((c) => c.gender === g.slug) ?? null;
            return (
              <section key={g.slug} aria-labelledby={`${id}-${g.slug}`} className="border-b border-line pb-2">
                <Link
                  id={`${id}-${g.slug}`}
                  href={`/products?gender=${g.slug}`}
                  onClick={onClose}
                  className={`${rowClass} text-base font-bold tracking-heading`}
                >
                  {g.label}
                </Link>
                {parent && parent.children.length > 0 && (
                  <ul aria-label={`${g.label} のカテゴリ`}>
                    {parent.children.map((child) => (
                      <li key={child.slug}>
                        <Link
                          href={`/products?${new URLSearchParams({ gender: g.slug, category: child.slug }).toString()}`}
                          onClick={onClose}
                          className={`${rowClass} pl-8 text-sm`}
                        >
                          <span>{child.name}</span>{" "}
                          <span className="text-xs text-fg-muted">{child.product_count}</span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            );
          })}

          {categories === null && (
            <p role="alert" className="px-4 py-3 text-sm text-fg-muted">
              カテゴリを読み込めませんでした。
            </p>
          )}

          <ul className="pt-2" aria-label="その他（P2）">
            {P2_LINKS.map((l) => (
              <li key={l.label}>
                <Link href={l.href} onClick={onClose} className={`${rowClass} text-sm text-fg-muted`}>
                  <span>{l.label}</span>{" "}
                  <span className="text-xs">P2</span>
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </div>
  );
}
