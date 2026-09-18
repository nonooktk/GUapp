"use client";

import { useEffect, useId, useRef } from "react";
import Button from "@/components/Button";

/**
 * 確認ダイアログ（設計仕様書 DS-PRC-036・REQ-FR-1205、デザイン基準 v1 3 章「確認ダイアログ」）。削除と Wave 2 の注文確定で使う。
 * - `role="dialog"`・`aria-modal`・`aria-labelledby`・`aria-describedby`
 * - 開いたらキャンセルボタンにフォーカス、Escape で閉じる、Tab はダイアログ内で循環
 * - `busy` 中はボタンを無効化して処理中表示（二重送信の使い勝手対策。防御は冪等キー側）
 * - ボタンはキャンセル = secondary、確定 = primary（`destructive` なら danger）。影はモーダルだけ --shadow-modal
 */

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 破壊的操作なら赤い確定ボタンにする */
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "OK",
  cancelLabel = "キャンセル",
  destructive = false,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();
  const descId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    return () => previous?.focus?.();
  }, [open]);

  if (!open) return null;

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape" && !busy) {
      e.preventDefault();
      onCancel();
      return;
    }
    if (e.key === "Tab" && panelRef.current) {
      const focusables = panelRef.current.querySelectorAll<HTMLElement>("button:not([disabled])");
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

  return (
    <div
      className="fixed inset-0 z-[60] flex items-end justify-center bg-overlay p-4 sm:items-center"
      onClick={() => !busy && onCancel()}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        className="w-full max-w-sm rounded-sm bg-bg p-6 shadow-modal"
      >
        <h2 id={titleId} className="text-lg font-bold tracking-heading text-fg">
          {title}
        </h2>
        {description && (
          <p id={descId} className="mt-2 text-sm text-fg-muted">
            {description}
          </p>
        )}
        <div className="mt-6 flex justify-end gap-2">
          <Button ref={cancelRef} variant="secondary" size="md" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant={destructive ? "danger" : "primary"} size="md" onClick={onConfirm} busy={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
