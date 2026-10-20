"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import AuthDemoNotice from "@/components/AuthDemoNotice";
import Button from "@/components/Button";
import { TextField } from "@/components/Form";
import { AUTH_FORM_MESSAGES, normalizeEmailInput } from "@/lib/auth-validation";
import { authErrorMessage } from "@/lib/auth-messages";
import { errorParts, login } from "@/lib/client/auth-api";
import { safeNext } from "@/lib/safe-next";

/**
 * ログイン DS-SCR-007（設計仕様書 6.3・3.1・DS-DEC-71・85、テスト UT-WEB-16・AT-13・AT-18）。
 * - 送信前にクライアントで必須だけを検査する。成功したら `next`（safeNext で許可リストに通した遷移先。無ければ /mypage）へ
 *   `router.replace` し、`router.refresh()` でヘッダー（会員アイコン）を描き直す
 * - 401 は「どちらが違うか」を書かない。403（ロック中）・429・503 は状態別の文言。入力済みのメールは残し、パスワードは空にする
 * - 送信中はボタン無効＋処理中表示で、連打しても 2 回目の送信をしない
 * - `resetDone`（?reset=1）のときは「パスワードを変更しました。ログインしてください」を出す
 */

export interface LoginFormProps {
  /** `?next=` の値（未検査でよい。ここでも safeNext を通す） */
  next?: string;
  resetDone?: boolean;
}

const linkClass = "inline-flex h-11 items-center text-sm underline underline-offset-2";

export default function LoginForm({ next, resetDone = false }: LoginFormProps) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (inflight.current) return;
    const em = normalizeEmailInput(email);
    const errs: { email?: string; password?: string } = {};
    if (em.length === 0) errs.email = AUTH_FORM_MESSAGES.required;
    if (password.length === 0) errs.password = AUTH_FORM_MESSAGES.required;
    setErrors(errs);
    setFormError(null);
    if (errs.email || errs.password) {
      document.getElementById(errs.email ? "login-email" : "login-password")?.focus();
      return;
    }

    inflight.current = true;
    setBusy(true);
    try {
      await login(em, password);
      // 成功: 遷移してからヘッダーを描き直す（busy は解かない）
      router.replace(safeNext(next));
      router.refresh();
    } catch (err) {
      const { status, body } = errorParts(err);
      setFormError(authErrorMessage(status, body));
      setPassword("");
      inflight.current = false;
      setBusy(false);
      document.getElementById("login-password")?.focus();
    }
  };

  return (
    <div className="mx-auto max-w-md space-y-6">
      <h1 className="text-xl font-light tracking-heading">ログイン</h1>
      <AuthDemoNotice />
      {resetDone && (
        <p role="status" className="rounded-sm border border-success bg-success/10 p-3 text-sm" data-testid="reset-done">
          パスワードを変更しました。ログインしてください
        </p>
      )}
      <form onSubmit={onSubmit} noValidate className="space-y-4" aria-label="ログイン">
        <TextField
          id="login-email"
          label="メールアドレス"
          required
          type="email"
          inputMode="email"
          autoComplete="username"
          placeholder="demo@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={errors.email}
        />
        <TextField
          id="login-password"
          label="パスワード"
          required
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
        />
        {formError && (
          <p role="alert" className="text-sm font-bold text-danger" data-testid="login-error">
            ⚠ {formError}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" full busy={busy} busyLabel="ログイン中…" data-testid="login-submit">
          ログイン
        </Button>
      </form>
      <ul className="space-y-1">
        <li>
          <Link href="/password-reset" className={linkClass}>
            パスワードをお忘れの方
          </Link>
        </li>
        <li>
          <Link href="/register" className={linkClass}>
            会員登録はこちら
          </Link>
        </li>
      </ul>
    </div>
  );
}
