"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Button from "@/components/Button";
import { SelectField, TextField } from "@/components/Form";
import { useToast } from "@/components/Toast";
import {
  mapServerFieldErrors,
  normalizeDigitsInput,
  PREFECTURES,
  validateCheckoutForm,
  type CheckoutErrors,
  type CheckoutField,
  type CheckoutFormValues,
} from "@/lib/checkout-validation";
import { CHECKOUT_KEY, clearCheckoutSession, saveCheckoutSession, type CheckoutSession } from "@/lib/checkout-session";
import { DEMO_CHECKOUT_FORM, DEMO_NOTICE_BODY, DEMO_NOTICE_TITLE } from "@/lib/demo-defaults";
import { parseJsonOrNull, useHydrated, useSessionItem } from "@/lib/client/use-session-item";
import { CartApiError } from "@/lib/client/cart-api";
import { prepareCheckout } from "@/lib/client/order-api";
import { routeOrderError } from "@/lib/order-errors";

/**
 * 注文手続き DS-SCR-005（設計仕様書 6.7・DS-PRC-014-1 入力形式、テスト AT-01・ST-F013-01/02、デザイン基準 v1 4 章 SCR-005）。
 * - 「会員の方（ログインは P2）」「ゲストで購入（既定）」の 2 カード。P1 はゲストのみ選べる
 * - お届け先: 氏名・郵便番号・都道府県・市区町村・番地・建物（任意）・電話・メール。1280px は氏名と電話を横並び、375px は 1 カラム
 * - 受け取り方法（配送のみ）・支払い方法（クレジットカード＝テスト決済のみ）はラジオカード。店舗受け取りは P2 として無効
 * - 「確認画面へ」: クライアント検査 → `POST /api/checkout/prepare` → 応答とフォーム値を sessionStorage に保存 → /checkout/confirm
 * - prepare の 409／404 は lib/order-errors.ts の戻し先へ。サーバーの 400 `fields` は同じ赤字表示に対応付ける
 * - デモの個人情報対策（P2 追補a 9.1 DS-DEC-47）: sessionStorage に復元値が無いときは `lib/demo-defaults.ts` の
 *   ダミー値を初期値にし、お届け先の直前に注意書きを常時表示する（本番でも出し分けない）
 */

const SECTION_TITLE = "text-lg font-light tracking-heading";

function RadioCard({
  name,
  value,
  checked,
  disabled,
  title,
  description,
  onChange,
  badge,
}: {
  name: string;
  value: string;
  checked: boolean;
  disabled?: boolean;
  title: string;
  description?: ReactNode;
  badge?: string;
  onChange?: () => void;
}) {
  const id = `${name}-${value}`;
  const frame = disabled
    ? "cursor-not-allowed border-line bg-line/40 text-disabled-fg"
    : checked
      ? "border-fg bg-bg"
      : "border-fg-muted bg-bg hover:bg-line/40";
  return (
    <label htmlFor={id} className={`flex cursor-pointer gap-3 rounded-sm border p-4 text-sm ${frame}`}>
      <input
        id={id}
        type="radio"
        name={name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        className="mt-0.5 size-5 shrink-0 accent-[var(--color-fg)]"
      />
      <span className="min-w-0">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-bold">{title}</span>
          {badge && <span className="rounded-pill border border-current px-2 text-xs">{badge}</span>}
        </span>
        {description && <span className="mt-1 block text-xs text-fg-muted">{description}</span>}
      </span>
    </label>
  );
}

/**
 * sessionStorage の復元値を初期値にしてフォームを組み立てる。サーバー描画・ハイドレーション中は空フォーム、
 * ハイドレーション後に key を変えて 1 回だけ作り直す（useEffect 内の setState を避け、SSR とも食い違わない）。
 */
export default function CheckoutForm() {
  const hydrated = useHydrated();
  const raw = useSessionItem(CHECKOUT_KEY);
  const session = useMemo(() => {
    const v = parseJsonOrNull<CheckoutSession>(raw);
    return v && typeof v.form === "object" && v.form !== null ? v : null;
  }, [raw]);
  return <CheckoutFormInner key={hydrated ? "client" : "server"} session={hydrated ? session : null} />;
}

function CheckoutFormInner({ session }: { session: CheckoutSession | null }) {
  const router = useRouter();
  const toast = useToast();
  // 確認画面から戻ったとき（戻る・price_changed・payment_failed・400）はフォーム値とサーバーエラーを復元する
  const [values, setValues] = useState<CheckoutFormValues>(() => ({ ...DEMO_CHECKOUT_FORM, ...(session?.form ?? {}) }));
  const [errors, setErrors] = useState<CheckoutErrors>(() => session?.serverErrors ?? {});
  const [submitting, setSubmitting] = useState(false);
  const paymentRef = useRef<HTMLElement>(null);
  const focusPayment = session?.focus === "payment";

  useEffect(() => {
    if (!session) return;
    if (focusPayment) {
      paymentRef.current?.scrollIntoView({ block: "center" });
      paymentRef.current?.focus();
    }
    // 復元した印（serverErrors・focus）は 1 回で消す（外部ストアへの書き込みだけ）
    if (session.serverErrors || session.focus) saveCheckoutSession({ form: session.form, prepare: session.prepare });
  }, [session, focusPayment]);

  const set = (field: CheckoutField, transform?: (s: string) => string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const raw = e.target.value;
    const next = transform ? transform(raw) : raw;
    setValues((v) => ({ ...v, [field]: next }));
    if (errors[field]) setErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  const focusFirstError = (errs: CheckoutErrors) => {
    const order: CheckoutField[] = ["name", "postal", "prefecture", "city", "street", "building", "phone", "email"];
    const first = order.find((f) => errs[f]);
    if (first) document.getElementById(`ship-${first}`)?.focus();
  };

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;
    const errs = validateCheckoutForm(values);
    setErrors(errs);
    if (Object.keys(errs).length > 0) {
      focusFirstError(errs);
      return;
    }
    setSubmitting(true);
    try {
      const prepare = await prepareCheckout();
      saveCheckoutSession({ form: values, prepare });
      router.push("/checkout/confirm");
    } catch (err) {
      const status = err instanceof CartApiError ? err.status : 0;
      const body = err instanceof CartApiError ? err.body : null;
      const route = routeOrderError(status, body);
      switch (route.kind) {
        case "field_errors": {
          const mapped = mapServerFieldErrors(route.fields);
          setErrors(mapped);
          focusFirstError(mapped);
          toast.show({ kind: "error", message: route.message });
          break;
        }
        case "cart": {
          toast.show({ kind: "error", message: route.message });
          const q = route.variantIds.length > 0 ? `?oos=${route.variantIds.join(",")}` : "";
          router.push(`/cart${q}`);
          break;
        }
        case "complete":
          clearCheckoutSession();
          toast.show({ kind: "info", message: route.message });
          router.push(`/orders/complete?n=${encodeURIComponent(route.orderNumber)}`);
          break;
        case "checkout":
        case "stay":
        default:
          toast.show({ kind: "error", message: route.message });
      }
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-10" aria-labelledby="checkout-heading">
      <h1 id="checkout-heading" className="text-xl font-light tracking-heading">
        ご注文手続き
      </h1>

      {/* 会員／ゲスト */}
      <section aria-labelledby="who-heading" className="space-y-3">
        <h2 id="who-heading" className={SECTION_TITLE}>
          ご購入方法
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <RadioCard name="who" value="member" checked={false} disabled title="会員の方" badge="P2 対応予定" description="ログインしてご購入（P1 では利用できません）" />
          <RadioCard name="who" value="guest" checked title="ゲストで購入" description="会員登録せずにそのまま進みます（P1 既定）" onChange={() => undefined} />
        </div>
      </section>

      {/* お届け先 */}
      <section aria-labelledby="ship-heading" className="space-y-4">
        <h2 id="ship-heading" className={SECTION_TITLE}>
          お届け先
        </h2>
        <div role="note" aria-label="デモに関する注意" className="rounded-sm border border-line bg-line/40 p-4 text-sm">
          <p className="font-bold">{DEMO_NOTICE_TITLE}</p>
          <p className="mt-1 text-fg-muted">{DEMO_NOTICE_BODY}</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            id="ship-name"
            label="氏名"
            required
            autoComplete="name"
            maxLength={60}
            placeholder="例: 山田 花子"
            value={values.name}
            onChange={set("name")}
            error={errors.name}
            hint="50 文字以内"
          />
          <TextField
            id="ship-phone"
            label="電話番号"
            required
            type="tel"
            inputMode="numeric"
            autoComplete="tel-national"
            placeholder="例: 090-1234-5678"
            value={values.phone}
            onChange={set("phone", normalizeDigitsInput)}
            error={errors.phone}
            hint="10〜11 桁。ハイフンは省略できます"
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            id="ship-postal"
            label="郵便番号"
            required
            inputMode="numeric"
            autoComplete="postal-code"
            placeholder="例: 100-0001"
            maxLength={8}
            value={values.postal}
            onChange={set("postal", normalizeDigitsInput)}
            error={errors.postal}
            hint="7 桁。ハイフンは省略できます"
          />
          <SelectField
            id="ship-prefecture"
            label="都道府県"
            required
            autoComplete="address-level1"
            value={values.prefecture}
            onChange={set("prefecture")}
            error={errors.prefecture}
          >
            <option value="">選択してください</option>
            {PREFECTURES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </SelectField>
        </div>
        <TextField
          id="ship-city"
          label="市区町村"
          required
          autoComplete="address-level2"
          placeholder="例: 千代田区"
          value={values.city}
          onChange={set("city")}
          error={errors.city}
        />
        <TextField
          id="ship-street"
          label="番地"
          required
          autoComplete="address-line1"
          placeholder="例: 千代田1-1"
          value={values.street}
          onChange={set("street")}
          error={errors.street}
        />
        <TextField
          id="ship-building"
          label="建物名・部屋番号"
          autoComplete="address-line2"
          placeholder="例: テストビル 101"
          value={values.building}
          onChange={set("building")}
          error={errors.building}
          hint="住所は合わせて 200 文字以内"
        />
        <TextField
          id="ship-email"
          label="メールアドレス"
          required
          type="email"
          inputMode="email"
          autoComplete="email"
          placeholder="例: hanako@example.com"
          value={values.email}
          onChange={set("email")}
          error={errors.email}
          hint="注文確認メールの送付先"
        />
      </section>

      {/* 受け取り方法 */}
      <section aria-labelledby="receive-heading" className="space-y-3">
        <h2 id="receive-heading" className={SECTION_TITLE}>
          受け取り方法
        </h2>
        <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-labelledby="receive-heading">
          <RadioCard name="receive" value="delivery" checked title="配送" description="ご指定のお届け先へお送りします" onChange={() => undefined} />
          <RadioCard name="receive" value="store" checked={false} disabled title="店舗受け取り" badge="P2 対応予定" />
        </div>
      </section>

      {/* 支払い方法 */}
      <section aria-labelledby="payment-heading" className="space-y-3 outline-none" ref={paymentRef} tabIndex={-1}>
        <h2 id="payment-heading" className={SECTION_TITLE}>
          支払い方法
        </h2>
        <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-labelledby="payment-heading">
          <RadioCard
            name="payment"
            value="card"
            checked
            title="クレジットカード"
            description="テスト決済です。カード番号の入力はありません"
            onChange={() => undefined}
          />
        </div>
      </section>

      {/* クーポン（P3） */}
      <section aria-labelledby="coupon-heading" className="space-y-3">
        <h2 id="coupon-heading" className={SECTION_TITLE}>
          クーポン <span className="ml-2 rounded-pill border border-fg-muted px-2 text-xs font-normal tracking-normal text-fg-muted">P3 対応予定</span>
        </h2>
        <div className="flex gap-2">
          <TextField id="coupon" label={<span className="sr-only">クーポンコード</span>} disabled placeholder="クーポンコード（P3 で対応予定）" />
          <Button variant="secondary" size="md" disabled className="mt-0 shrink-0 self-start">
            適用
          </Button>
        </div>
      </section>

      <div className="flex justify-end">
        <Button type="submit" variant="primary" size="lg" busy={submitting} busyLabel="確認中…" className="w-full sm:w-80" data-testid="to-confirm">
          確認画面へ
        </Button>
      </div>
    </form>
  );
}
