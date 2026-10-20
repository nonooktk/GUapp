"use client";

import { useRef, useState } from "react";
import Button from "@/components/Button";
import { TextField } from "@/components/Form";
import { AUTH_FORM_MESSAGES, normalizeEmailInput } from "@/lib/auth-validation";
import { errorParts } from "@/lib/client/auth-api";
import { registerRestock } from "@/lib/client/restock-api";
import { isValidEmail } from "@/lib/checkout-validation";
import { RESTOCK_MESSAGES, restockErrorMessage } from "@/lib/restock-messages";

/**
 * 再入荷のお知らせ申込 DS-SCR-003（設計仕様書 6.6・DS-API-007・DS-DEC-80、テスト UT-WEB-23・AT-16）。
 * PurchasePanel が、色とサイズの両方が選ばれ、その組み合わせが在庫切れのときだけ在庫表示の下に出す。
 * メール欄とボタン。送信中は無効化。200 は欄を消して「申し込みました…」。409／404／422／400／429 は lib/restock-messages.ts の文言。
 * 組み合わせ（variant）が変わったら親が `key` を変えて作り直す（申込済みの表示を持ち越さない）。
 */

export default function RestockForm({ variantId }: { variantId: number }) {
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | undefined>();
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
      setEmailError(AUTH_FORM_MESSAGES.required);
      return;
    }
    if (!isValidEmail(em)) {
      setEmailError(RESTOCK_MESSAGES.invalidEmail);
      return;
    }
    setEmailError(undefined);
    inflight.current = true;
    setBusy(true);
    try {
      await registerRestock(variantId, em);
      setDone(true);
    } catch (err) {
      const { status, body } = errorParts(err);
      const r = restockErrorMessage(status, body);
      if (r.kind === "email") setEmailError(r.message);
      else setFormError(r.message);
      inflight.current = false;
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="restock-heading" className="space-y-3 rounded-sm border border-line bg-line/40 p-4" data-testid="restock-form">
      <h3 id="restock-heading" className="text-sm font-bold">
        再入荷のお知らせ
      </h3>
      {done ? (
        <p role="status" className="text-sm" data-testid="restock-done">
          {RESTOCK_MESSAGES.done}
        </p>
      ) : (
        <form onSubmit={onSubmit} noValidate className="space-y-3" aria-label="再入荷のお知らせ">
          <p className="text-xs text-fg-muted">入荷したらメールでお知らせします。</p>
          <TextField
            id="restock-email"
            label="メールアドレス"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="demo@example.com"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setEmailError(undefined);
            }}
            error={emailError}
          />
          {formError && (
            <p role="alert" className="text-sm font-bold text-danger" data-testid="restock-error">
              ⚠ {formError}
            </p>
          )}
          <Button type="submit" variant="secondary" size="md" full busy={busy} busyLabel="送信中…" data-testid="restock-submit">
            お知らせを申し込む
          </Button>
        </form>
      )}
    </section>
  );
}
