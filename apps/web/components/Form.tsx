import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

/**
 * 入力欄・セレクト・エラー表示（デザイン基準 v1 3 章「入力欄・セレクト」、SCR-005 向け）。
 * - 高さ 44px・角丸 8px・枠線 --color-line、フォーカスで枠線 --color-fg（outline は全部品共通のものが付く）
 * - ラベルは項目名の上（--text-sm・700）。必須は「（必須）」のテキストで示す（色やアイコンに頼らない）
 * - エラー時は `aria-invalid` で枠線を --color-danger にし、直下に `role="alert"` の赤文字（--text-sm）。
 *   入力欄とは `aria-describedby` で結ぶ
 * 数量セレクトのようにラベルを別に持つ場合は `controlClass` だけを使う。
 */

/** 入力欄・セレクト共通の見た目（幅は呼び出し側で決める） */
export const controlClass =
  "h-11 rounded-sm border border-line bg-bg px-3 text-sm text-fg focus:border-fg aria-invalid:border-danger disabled:cursor-not-allowed disabled:bg-line/40 disabled:text-disabled-fg";

interface FieldShellProps {
  id: string;
  label: ReactNode;
  required?: boolean;
  /** 補足説明（入力欄の下、エラーの前） */
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
}

function FieldShell({ id, label, required, hint, error, children }: FieldShellProps) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-bold text-fg">
        {label}
        {required && <span className="ml-1 font-normal text-fg-muted">（必須）</span>}
      </label>
      {children}
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-xs text-fg-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="mt-1 text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

function describedBy(id: string, hint: unknown, error: unknown): string | undefined {
  const ids = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean);
  return ids.length > 0 ? ids.join(" ") : undefined;
}

export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "required"> {
  id: string;
  label: ReactNode;
  required?: boolean;
  hint?: ReactNode;
  error?: ReactNode;
}

export function TextField({ id, label, required, hint, error, className = "", ...rest }: TextFieldProps) {
  return (
    <FieldShell id={id} label={label} required={required} hint={hint} error={error}>
      <input
        {...rest}
        id={id}
        aria-required={required || undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        className={`${controlClass} w-full ${className}`}
      />
    </FieldShell>
  );
}

export interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "id" | "required"> {
  id: string;
  label: ReactNode;
  required?: boolean;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
}

export function SelectField({ id, label, required, hint, error, className = "", children, ...rest }: SelectFieldProps) {
  return (
    <FieldShell id={id} label={label} required={required} hint={hint} error={error}>
      <select
        {...rest}
        id={id}
        aria-required={required || undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, hint, error)}
        className={`${controlClass} w-full ${className}`}
      >
        {children}
      </select>
    </FieldShell>
  );
}
