"use client";

import { useEffect, useRef } from "react";
import SearchBox from "@/components/SearchBox";

/**
 * モバイル（375px）の検索パネル（設計仕様書 P2 追補a 6.1）。
 * 常設の入力欄を置く横幅が無いため、`AllMenu` と同じ「オーバーレイ＋フォーカストラップ＋
 * Escape で閉じる」パターンで開閉する。閉じたら検索アイコンへフォーカスを戻すのは呼び出し側（Header）の責務。
 */

export interface SearchPanelProps {
  id: string;
  open: boolean;
  onClose: () => void;
}

const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled])";

export default function SearchPanel({ id, open, onClose }: SearchPanelProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
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
    <div className="fixed inset-0 z-[60] flex bg-overlay" onClick={onClose} data-testid="search-panel-overlay">
      <div
        id={id}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        className="flex w-full flex-col bg-bg shadow-modal"
      >
        <div className="flex h-16 shrink-0 items-center gap-2 border-b border-line px-4">
          <h2 id={titleId} className="sr-only">
            商品を検索
          </h2>
          <SearchBox autoFocus className="flex-1" onNavigate={onClose} onEscape={onClose} />
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="inline-flex size-11 shrink-0 items-center justify-center rounded-pill text-fg hover:bg-line"
            aria-label="検索を閉じる"
          >
            <span aria-hidden="true" className="text-xl leading-none">
              ×
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
