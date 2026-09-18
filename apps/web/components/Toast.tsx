"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

/**
 * トースト（設計仕様書 DS-PRC-036、デザイン基準 v1 3 章「トースト」）。成功・失敗を画面下部に数秒表示する。
 * `useToast().show({ kind, message, action? })` で呼ぶ。`role="status"`＋`aria-live="polite"` で読み上げ対象にする。
 * 色は kind ごとに --color-success／--color-danger／--color-fg-muted の枠線＋薄い背景、文字は --color-fg（コントラスト確保）。
 * Wave 2 の注文確定でもそのまま使う。
 */

export type ToastKind = "success" | "error" | "info";

export interface ToastAction {
  label: string;
  href: string;
}

export interface ToastInput {
  kind: ToastKind;
  message: string;
  /** 「カートを見る」のような導線。任意 */
  action?: ToastAction;
  /** 表示時間（ms）。既定 4000 */
  durationMs?: number;
}

interface ToastItem extends ToastInput {
  id: number;
}

interface ToastContextValue {
  show: (input: ToastInput) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast は ToastProvider の内側で使ってください");
  return ctx;
}

const KIND_CLASS: Record<ToastKind, string> = {
  success: "border-success bg-success/10",
  error: "border-danger bg-danger/10",
  info: "border-fg-muted bg-line/40",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (input: ToastInput) => {
      const id = ++seq.current;
      setItems((prev) => [...prev.slice(-2), { ...input, id }]);
      window.setTimeout(() => dismiss(id), input.durationMs ?? 4000);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ show, dismiss }), [show, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed inset-x-0 bottom-24 z-50 flex flex-col items-center gap-2 px-4 sm:bottom-6"
      >
        {items.map((t) => (
          <div
            key={t.id}
            data-testid="toast"
            data-kind={t.kind}
            className={`pointer-events-auto flex w-full max-w-md items-center justify-between gap-3 rounded-sm border bg-bg px-4 py-2 text-sm text-fg ${KIND_CLASS[t.kind]}`}
          >
            <span className="py-1">{t.message}</span>
            <span className="flex shrink-0 items-center gap-1">
              {t.action && (
                <a href={t.action.href} className="inline-flex h-11 items-center px-2 font-bold underline underline-offset-2">
                  {t.action.label}
                </a>
              )}
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="通知を閉じる"
                className="inline-flex size-11 items-center justify-center rounded-pill hover:bg-line"
              >
                <span aria-hidden="true">×</span>
              </button>
            </span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
