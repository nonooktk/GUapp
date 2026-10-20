"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import AuthDemoNotice from "@/components/AuthDemoNotice";
import Button from "@/components/Button";
import { TextField } from "@/components/Form";
import { AUTH_MESSAGES, authErrorMessage } from "@/lib/auth-messages";
import { AUTH_FORM_MESSAGES, normalizeEmailInput, validateResetConfirm } from "@/lib/auth-validation";
import { confirmPasswordReset, errorParts, requestPasswordReset } from "@/lib/client/auth-api";
import { isValidEmail } from "@/lib/checkout-validation";

/**
 * パスワード再設定 DS-SCR-007（設計仕様書 6.3・DS-API-034・035・DS-DEC-71・75、テスト UT-WEB-18・AT-19）。
 * - 要求（/password-reset）: メール 1 欄。送信後は登録の有無を区別せず常に同じ案内を出す（200）
 * - 確定（/password-reset/confirm?token=…）: 新しいパスワードと確認入力（一致の検査はクライアントだけ）。
 *   404 は「リンクが無効か、期限が切れています」と再要求へのリンク。成功したら /login?reset=1 へ移す（自動ログインしない）
 */

const linkClass = "inline-flex h-11 items-center text-sm underline underline-offset-2";

export function PasswordResetRequestForm() {
  const [email, setEmail] = useState("");
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const inflight = useRef(false);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (inflight.current) return;
    const em = normalizeEmailInput(email);
    setFormError(null);
    if (em.length === 0) {
      setFieldError(AUTH_FORM_MESSAGES.required);
      return;
    }
    if (!isValidEmail(em)) {
      setFieldError(AUTH_FORM_MESSAGES.email);
      return;
    }
    setFieldError(undefined);
    inflight.current = true;
    setBusy(true);
    try {
      await requestPasswordReset(em);
      setDone(true);
    } catch (err) {
      const { status, body } = errorParts(err);
      if (status === 422 && body?.code === "unsupported_value") setFieldError(authErrorMessage(status, body));
      else if (status === 400) setFieldError(AUTH_FORM_MESSAGES.email);
      else setFormError(authErrorMessage(status, body));
      inflight.current = false;
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-md space-y-6">
      <h1 className="text-xl font-light tracking-heading">パスワードの再設定</h1>
      <AuthDemoNotice />
      {done ? (
        <p role="status" className="rounded-sm border border-success bg-success/10 p-4 text-sm" data-testid="reset-request-done">
          入力されたメールアドレスが登録されていれば、再設定のメールを送りました
        </p>
      ) : (
        <form onSubmit={onSubmit} noValidate className="space-y-4" aria-label="パスワードの再設定">
          <p className="text-sm text-fg-muted">登録したメールアドレスを入力してください。再設定用のリンクをお送りします。</p>
          <TextField
            id="reset-email"
            label="メールアドレス"
            required
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="demo@example.com"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setFieldError(undefined);
            }}
            error={fieldError}
          />
          {formError && (
            <p role="alert" className="text-sm font-bold text-danger" data-testid="reset-request-error">
              ⚠ {formError}
            </p>
          )}
          <Button type="submit" variant="primary" size="lg" full busy={busy} busyLabel="送信中…" data-testid="reset-request-submit">
            再設定のメールを送る
          </Button>
        </form>
      )}
      <Link href="/login" className={linkClass}>
        ログイン画面へ戻る
      </Link>
    </div>
  );
}

export function PasswordResetConfirmForm({ token }: { token: string }) {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<{ password?: string; confirm?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [invalidLink, setInvalidLink] = useState(false);
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (inflight.current) return;
    const errs = validateResetConfirm({ password, confirm });
    setErrors(errs);
    setFormError(null);
    if (errs.password || errs.confirm) {
      document.getElementById(errs.password ? "reset-password" : "reset-confirm")?.focus();
      return;
    }
    inflight.current = true;
    setBusy(true);
    try {
      await confirmPasswordReset(token, password);
      router.replace("/login?reset=1");
    } catch (err) {
      const { status, body } = errorParts(err);
      if (status === 404) setInvalidLink(true);
      else if (status === 422 && body?.code === "weak_password") setErrors({ password: authErrorMessage(status, body) });
      else if (status === 400) setErrors({ password: AUTH_FORM_MESSAGES.password });
      else setFormError(authErrorMessage(status, body));
      inflight.current = false;
      setBusy(false);
    }
  };

  if (invalidLink) return <InvalidLinkNotice />;

  return (
    <div className="mx-auto max-w-md space-y-6">
      <h1 className="text-xl font-light tracking-heading">新しいパスワードの設定</h1>
      <form onSubmit={onSubmit} noValidate className="space-y-4" aria-label="新しいパスワードの設定">
        <TextField
          id="reset-password"
          label="新しいパスワード（8〜128 文字）"
          required
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
            setErrors((p) => ({ ...p, password: undefined }));
          }}
          error={errors.password}
        />
        <TextField
          id="reset-confirm"
          label="新しいパスワード（確認）"
          required
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => {
            setConfirm(e.target.value);
            setErrors((p) => ({ ...p, confirm: undefined }));
          }}
          error={errors.confirm}
        />
        {formError && (
          <p role="alert" className="text-sm font-bold text-danger" data-testid="reset-confirm-error">
            ⚠ {formError}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" full busy={busy} busyLabel="変更中…" data-testid="reset-confirm-submit">
          パスワードを変更する
        </Button>
      </form>
    </div>
  );
}

/** token が無い・形が違う・404 のときの案内（再要求などへのリンクつき）。再設定とメール確認で共用 */
export function InvalidLinkNotice({
  title = "パスワードの再設定",
  href = "/password-reset",
  linkLabel = "再設定のメールをもう一度送る",
}: {
  title?: string;
  href?: string;
  linkLabel?: string;
}) {
  return (
    <div className="mx-auto max-w-md space-y-4" data-testid="invalid-link">
      <h1 className="text-xl font-light tracking-heading">{title}</h1>
      <p role="alert" className="text-sm font-bold text-danger">
        ⚠ {AUTH_MESSAGES.invalidLink}
      </p>
      <Link href={href} className={linkClass}>
        {linkLabel}
      </Link>
    </div>
  );
}
