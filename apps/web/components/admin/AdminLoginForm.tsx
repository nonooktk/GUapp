"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import Button from "@/components/Button";
import { TextField } from "@/components/Form";
import { ADMIN_MESSAGES, adminErrorMessage } from "@/lib/admin-messages";
import { ADMIN_HOME_PATH } from "@/lib/admin-types";
import { adminErrorParts, adminLogin } from "@/lib/client/admin-api";

/**
 * 管理ログイン DS-SCR-014（設計仕様書 P2 追補c 6.3・3.1・DS-DEC-110・121、テスト UT-WEB-42・AT-30）。
 * - 顧客向けのヘッダー・フッターは出さない。公開サイトへのリンクも置かない
 * - 送信前にクライアントで必須だけを検査する。送信の前に `GET /admin/api/csrf` で `csrf_token` を用意する（admin-api.ts）
 * - 成功したら**常に** `/admin/products` へ `router.replace` し、`router.refresh()`。遷移先の指定（`next`）は受けない
 * - 401 は「ID とパスワードのどちらが違うか」を書かない。403（ロック中）・429・503 は状態別の文言。ID は残し、パスワードは空にする
 * - 送信中はボタン無効＋処理中表示で、連打しても 2 回目の送信をしない
 * - `expired`（`?expired=1`）のときは「セッションの有効期限が切れました。もう一度ログインしてください」を上部に出す
 */

export interface AdminLoginFormProps {
  expired?: boolean;
}

export default function AdminLoginForm({ expired = false }: AdminLoginFormProps) {
  const router = useRouter();
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ loginId?: string; password?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (inflight.current) return;
    const id = loginId.trim();
    const errs: { loginId?: string; password?: string } = {};
    if (id.length === 0) errs.loginId = "入力してください";
    if (password.length === 0) errs.password = "入力してください"; // pragma: allowlist secret（エラー文言。秘密ではない）
    setErrors(errs);
    setFormError(null);
    if (errs.loginId || errs.password) {
      document.getElementById(errs.loginId ? "admin-login-id" : "admin-login-password")?.focus();
      return;
    }

    inflight.current = true;
    setBusy(true);
    try {
      await adminLogin(id, password);
      // 成功: 遷移してから描き直す（busy は解かない）。遷移先は固定
      router.replace(ADMIN_HOME_PATH);
      router.refresh();
    } catch (err) {
      const { status, body } = adminErrorParts(err);
      setFormError(adminErrorMessage(status, body));
      setPassword("");
      inflight.current = false;
      setBusy(false);
      document.getElementById("admin-login-password")?.focus();
    }
  };

  return (
    <div className="mx-auto max-w-md space-y-6 py-8">
      <h1 className="text-xl font-light tracking-heading">管理者ログイン</h1>
      {expired && (
        <p role="status" className="rounded-sm border border-danger bg-danger/10 p-3 text-sm" data-testid="admin-expired">
          {ADMIN_MESSAGES.loginExpiredNotice}
        </p>
      )}
      <form onSubmit={onSubmit} noValidate className="space-y-4" aria-label="管理者ログイン">
        <TextField
          id="admin-login-id"
          label="ログイン ID"
          required
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          value={loginId}
          onChange={(e) => setLoginId(e.target.value)}
          error={errors.loginId}
        />
        <TextField
          id="admin-login-password"
          label="パスワード"
          required
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
        />
        {formError && (
          <p role="alert" className="text-sm font-bold text-danger" data-testid="admin-login-error">
            ⚠ {formError}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" full busy={busy} busyLabel="ログイン中…" data-testid="admin-login-submit">
          ログイン
        </Button>
      </form>
    </div>
  );
}
