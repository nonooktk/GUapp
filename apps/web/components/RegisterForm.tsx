"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import AuthDemoNotice from "@/components/AuthDemoNotice";
import Button, { buttonClass } from "@/components/Button";
import { SelectField, TextField } from "@/components/Form";
import { authErrorMessage, mapRegisterFieldErrors, type RegisterErrors } from "@/lib/auth-messages";
import { normalizeEmailInput, validateRegisterForm } from "@/lib/auth-validation";
import { errorParts, register, type RegisterInput } from "@/lib/client/auth-api";

/**
 * 会員登録 DS-SCR-007（設計仕様書 6.3・DS-API-030・DS-DEC-69・71・76、テスト UT-WEB-17・AT-13）。
 * - クライアントでもメール形式・パスワード 8〜128 文字（NFKC 後）・氏名 1〜50 文字を検査し、サーバーの 400 `fields` は項目ごとに表示する
 * - 422 `weak_password` はパスワード欄、422 `unsupported_value` はメール欄に出す
 * - 202 のときはフォームを消して「登録を受け付けました…」と /login へのリンクを出す（新規・既登録を区別しない。自動ログインしない）
 * - 注意書き（デモ）を常時表示する。メール欄の入力例は demo@example.com
 */

const GENDERS = [
  { value: "female", label: "女性" },
  { value: "male", label: "男性" },
  { value: "other", label: "その他" },
  { value: "no_answer", label: "回答しない" },
] as const;

export default function RegisterForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [gender, setGender] = useState("");
  const [personalize, setPersonalize] = useState(false);
  const [errors, setErrors] = useState<RegisterErrors>({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const inflight = useRef(false);

  const clear = (key: keyof RegisterErrors) => () => setErrors((prev) => ({ ...prev, [key]: undefined }));

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (inflight.current) return;
    const errs = validateRegisterForm({ email, password, name, birthDate, gender });
    setErrors(errs);
    if (Object.keys(errs).length > 0) {
      const order: [keyof RegisterErrors, string][] = [
        ["email", "register-email"],
        ["password", "register-password"],
        ["name", "register-name"],
        ["birth_date", "register-birth"],
      ];
      const first = order.find(([k]) => errs[k]);
      if (first) document.getElementById(first[1])?.focus();
      return;
    }

    inflight.current = true;
    setBusy(true);
    const input: RegisterInput = { email: normalizeEmailInput(email), password, name: name.trim() };
    if (birthDate) input.birth_date = birthDate;
    if (gender) input.gender = gender;
    if (personalize) input.personalize_opt_in = true;
    try {
      await register(input);
      setDone(true);
    } catch (err) {
      const { status, body } = errorParts(err);
      const next: RegisterErrors = {};
      if (status === 400 && body?.code === "validation_error") {
        Object.assign(next, mapRegisterFieldErrors(body.fields));
        if (Object.keys(next).length === 0) next.form = authErrorMessage(status, body);
      } else if (status === 422 && body?.code === "weak_password") {
        next.password = authErrorMessage(status, body);
      } else if (status === 422 && body?.code === "unsupported_value") {
        next.email = authErrorMessage(status, body);
      } else {
        next.form = authErrorMessage(status, body);
      }
      setErrors(next);
      inflight.current = false;
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="mx-auto max-w-md space-y-6">
        <h1 className="text-xl font-light tracking-heading">会員登録</h1>
        <div role="status" className="space-y-2 rounded-sm border border-success bg-success/10 p-4 text-sm" data-testid="register-done">
          <p className="font-bold">登録を受け付けました</p>
          <p>ログイン画面からログインしてください。確認メールを送っています。</p>
        </div>
        <Link href="/login" className={buttonClass({ variant: "primary", size: "lg", full: true })}>
          ログイン画面へ
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-md space-y-6">
      <h1 className="text-xl font-light tracking-heading">会員登録</h1>
      <AuthDemoNotice />
      <form onSubmit={onSubmit} noValidate className="space-y-4" aria-label="会員登録">
        <TextField
          id="register-email"
          label="メールアドレス"
          required
          type="email"
          inputMode="email"
          autoComplete="email"
          placeholder="demo@example.com"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
            clear("email")();
          }}
          error={errors.email}
        />
        <TextField
          id="register-password"
          label="パスワード（8〜128 文字）"
          required
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
            clear("password")();
          }}
          error={errors.password}
          hint="よくあるパスワードやメールアドレスと同じ値は使えません"
        />
        <TextField
          id="register-name"
          label="氏名"
          required
          autoComplete="name"
          maxLength={60}
          placeholder="例: デモ 太郎"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            clear("name")();
          }}
          error={errors.name}
          hint="50 文字以内"
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            id="register-birth"
            label="生年月日（任意）"
            type="date"
            min="1900-01-01"
            autoComplete="bday"
            value={birthDate}
            onChange={(e) => {
              setBirthDate(e.target.value);
              clear("birth_date")();
            }}
            error={errors.birth_date}
          />
          <SelectField
            id="register-gender"
            label="性別（任意）"
            value={gender}
            onChange={(e) => {
              setGender(e.target.value);
              clear("gender")();
            }}
            error={errors.gender}
          >
            <option value="">未選択</option>
            {GENDERS.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </SelectField>
        </div>
        <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
          <input
            type="checkbox"
            checked={personalize}
            onChange={(e) => setPersonalize(e.target.checked)}
            className="size-5 shrink-0 accent-[var(--color-fg)]"
          />
          <span>おすすめの表示に使う（任意）</span>
        </label>
        {errors.form && (
          <p role="alert" className="text-sm font-bold text-danger" data-testid="register-error">
            ⚠ {errors.form}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" full busy={busy} busyLabel="登録中…" data-testid="register-submit">
          登録する
        </Button>
      </form>
      <p className="text-sm">
        <Link href="/login" className="inline-flex h-11 items-center underline underline-offset-2">
          すでに会員の方はログイン
        </Link>
      </p>
    </div>
  );
}
