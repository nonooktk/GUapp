import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";

/**
 * ボタン（デザイン基準 v1 3 章「ボタン」）。
 * - primary: 黒背景・白文字・ピル。カートに入れる／レジへ進む／注文を確定する
 * - secondary: 白背景・黒枠・ピル。買い物を続ける／もっと見る／キャンセル
 * - ghost: 背景なし・hover で下線。テキストリンク的な操作
 * - danger: 赤背景・白文字。削除確認の確定
 * - size lg = 52px（主要 CTA）／md = 44px（タッチターゲット最小）
 * - `busy` 中はラベルを `busyLabel`（既定「処理中…」）に差し替え、`aria-busy` を付けてクリック不可にする
 * `<Link>` に同じ見た目を当てたいときは `buttonClass()` を className に渡す。
 */

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "lg" | "md";

const BASE =
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-pill text-sm font-bold transition-colors disabled:cursor-not-allowed";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-fg hover:bg-primary-hover disabled:bg-disabled-bg disabled:text-disabled-fg",
  secondary:
    "border border-fg bg-bg text-fg hover:bg-line disabled:border-disabled-bg disabled:text-disabled-fg disabled:hover:bg-bg",
  ghost: "bg-transparent text-fg hover:underline disabled:text-disabled-fg disabled:no-underline",
  danger: "bg-danger text-primary-fg hover:brightness-90 disabled:bg-disabled-bg disabled:text-disabled-fg",
};

const SIZE: Record<ButtonSize, string> = {
  lg: "h-13 px-6",
  md: "h-11 px-5",
};

export interface ButtonClassOptions {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** 横幅いっぱい */
  full?: boolean;
  className?: string;
}

/** ボタンの見た目だけを返す（`<Link>` や `<a>` に付ける用） */
export function buttonClass({ variant = "primary", size = "lg", full = false, className = "" }: ButtonClassOptions = {}): string {
  return [BASE, VARIANT[variant], SIZE[size], full ? "w-full" : "", className].filter(Boolean).join(" ");
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, Omit<ButtonClassOptions, "className"> {
  /** 処理中。true の間は無効化してラベルを `busyLabel` にする */
  busy?: boolean;
  busyLabel?: ReactNode;
  children: ReactNode;
  /** React 19 では ref を props として受け取れる（ConfirmDialog の初期フォーカス用） */
  ref?: Ref<HTMLButtonElement>;
}

export default function Button({
  variant = "primary",
  size = "lg",
  full = false,
  busy = false,
  busyLabel = "処理中…",
  disabled,
  type = "button",
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      disabled={disabled || busy}
      aria-busy={busy}
      className={buttonClass({ variant, size, full, className })}
    >
      {busy ? busyLabel : children}
    </button>
  );
}
