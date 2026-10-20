"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Button, { buttonClass } from "@/components/Button";
import { SelectField, TextField } from "@/components/Form";
import { useToast } from "@/components/Toast";
import {
  ADDRESS_FIELDS,
  mapServerFieldErrors,
  normalizeDigitsInput,
  PREFECTURES,
  validateCheckoutForm,
  type CheckoutErrors,
  type CheckoutField,
  type CheckoutFormValues,
} from "@/lib/checkout-validation";
import { carryReceive, CHECKOUT_KEY, clearCheckoutSession, saveCheckoutSession, type CheckoutSession } from "@/lib/checkout-session";
import { DEMO_CHECKOUT_FORM, DEMO_NOTICE_BODY, DEMO_NOTICE_TITLE } from "@/lib/demo-defaults";
import { parseJsonOrNull, useHydrated, useSessionItem } from "@/lib/client/use-session-item";
import { CartApiError } from "@/lib/client/cart-api";
import { prepareCheckout } from "@/lib/client/order-api";
import { routeOrderError } from "@/lib/order-errors";
import type { ReceiveMethod, StoreSummary } from "@/lib/types";

/**
 * 注文手続き DS-SCR-005（設計仕様書 6.7・DS-PRC-014-1 入力形式、テスト AT-01・ST-F013-01/02、デザイン基準 v1 4 章 SCR-005）。
 * - 未ログイン: 「会員の方（ログイン → /login?next=/checkout）」「ゲストで購入（既定）」の 2 カード。
 *   ログイン中: 「ログイン中: ○○ 様」のカード（ゲストのカードは出さない）。氏名・メールは会員情報（props）を初期値にする（変更できる）
 * - 受け取り方法: 配送／店舗受け取り（P2-b）。店舗では郵便番号・都道府県・市区町村・番地・建物の欄を隠し（検査も送信もしない）、
 *   受け取り店舗のセレクトを出す。店舗一覧は /checkout の Server Component が取得して props で渡す（失敗は null＝店舗受け取りは選べない）
 * - お届け先／受け取る方: 氏名・郵便番号・都道府県・市区町村・番地・建物（任意）・電話・メール。1280px は氏名と電話を横並び、375px は 1 カラム
 * - 支払い方法（クレジットカード＝テスト決済のみ）はラジオカード
 * - 「確認画面へ」: クライアント検査 → `POST /api/checkout/prepare`（receive_method つき）→ 応答・フォーム値・受け取り方法・店舗を sessionStorage に保存 → /checkout/confirm
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
export interface CheckoutFormProps {
  /** ログイン中の会員（`GET /me` の氏名・メール）。未ログイン・取得失敗は null */
  member?: { name: string; email: string } | null;
  /** 受け取り店舗の一覧（`GET /stores`）。取得失敗は null（店舗受け取りは選べない） */
  stores?: StoreSummary[] | null;
}

export default function CheckoutForm({ member = null, stores = null }: CheckoutFormProps) {
  const hydrated = useHydrated();
  const raw = useSessionItem(CHECKOUT_KEY);
  const session = useMemo(() => {
    const v = parseJsonOrNull<CheckoutSession>(raw);
    return v && typeof v.form === "object" && v.form !== null ? v : null;
  }, [raw]);
  return <CheckoutFormInner key={hydrated ? "client" : "server"} session={hydrated ? session : null} member={member} stores={stores} />;
}

/** 復元値（無ければダミー値。ログイン中は氏名・メールを会員情報にする）でフォームの初期値を作る */
function initialValues(session: CheckoutSession | null, member: CheckoutFormProps["member"]): CheckoutFormValues {
  const base: CheckoutFormValues = {
    ...DEMO_CHECKOUT_FORM,
    ...(member ? { name: member.name, email: member.email } : {}),
    ...(session?.form ?? {}),
  };
  // 店舗受け取りで保存した値は住所の欄が空。配送に切り替えたときの初期値はダミー値に戻す
  if (session?.receive_method === "store") {
    for (const f of ADDRESS_FIELDS) base[f] = DEMO_CHECKOUT_FORM[f];
  }
  return base;
}

function CheckoutFormInner({
  session,
  member,
  stores,
}: {
  session: CheckoutSession | null;
  member: NonNullable<CheckoutFormProps["member"]> | null;
  stores: StoreSummary[] | null;
}) {
  const router = useRouter();
  const toast = useToast();
  const storesAvailable = stores !== null && stores.length > 0;
  // 確認画面から戻ったとき（戻る・price_changed・payment_failed・400）はフォーム値とサーバーエラーを復元する
  const [values, setValues] = useState<CheckoutFormValues>(() => initialValues(session, member));
  const [errors, setErrors] = useState<CheckoutErrors>(() => session?.serverErrors ?? {});
  const restoredStore = session?.receive_method === "store" && stores?.some((s) => s.code === session.store_code) ? session.store_code : undefined;
  const [receive, setReceive] = useState<ReceiveMethod>(() => (restoredStore && storesAvailable ? "store" : "delivery"));
  const [storeCode, setStoreCode] = useState<string>(() => restoredStore ?? "");
  const [storeError, setStoreError] = useState<string | undefined>(undefined);
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
    if (session.serverErrors || session.focus) {
      saveCheckoutSession({ form: session.form, prepare: session.prepare, ...carryReceive(session) });
    }
  }, [session, focusPayment]);

  const set = (field: CheckoutField, transform?: (s: string) => string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const raw = e.target.value;
    const next = transform ? transform(raw) : raw;
    setValues((v) => ({ ...v, [field]: next }));
    if (errors[field]) setErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  const focusFirstError = (errs: CheckoutErrors, storeErr?: string) => {
    if (storeErr) {
      document.getElementById("ship-store")?.focus();
      return;
    }
    // 画面の並び順（氏名・電話 → 住所 → メール）
    const order: CheckoutField[] = ["name", "phone", "postal", "prefecture", "city", "street", "building", "email"];
    const first = order.find((f) => errs[f]);
    if (first) document.getElementById(`ship-${first}`)?.focus();
  };

  const selectedStore = receive === "store" ? (stores?.find((s) => s.code === storeCode) ?? null) : null;

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;
    const errs = validateCheckoutForm(values, receive);
    const storeErr = receive === "store" && !selectedStore ? "受け取り店舗を選択してください" : undefined;
    setErrors(errs);
    setStoreError(storeErr);
    if (Object.keys(errs).length > 0 || storeErr) {
      focusFirstError(errs, storeErr);
      return;
    }
    setSubmitting(true);
    try {
      const prepare = await prepareCheckout(receive);
      if (receive === "store" && selectedStore) {
        // 送信しない住所の値は残さない（保存値にも含めない）
        const form = { ...values, postal: "", prefecture: "", city: "", street: "", building: "" };
        saveCheckoutSession({ form, prepare, receive_method: "store", store_code: selectedStore.code, store: selectedStore });
      } else {
        saveCheckoutSession({ form: values, prepare, receive_method: "delivery" });
      }
      router.push("/checkout/confirm");
    } catch (err) {
      const status = err instanceof CartApiError ? err.status : 0;
      const body = err instanceof CartApiError ? err.body : null;
      const route = routeOrderError(status, body);
      switch (route.kind) {
        case "field_errors": {
          const mapped = mapServerFieldErrors(route.fields);
          const storeErr =
            receive === "store" && Array.isArray(route.fields) && route.fields.some((f) => (f as { name?: unknown } | null)?.name === "store_code")
              ? "受け取り店舗を選択してください"
              : undefined;
          setErrors(mapped);
          setStoreError(storeErr);
          focusFirstError(mapped, storeErr);
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

  const isStore = receive === "store";
  const onSelectReceive = (m: ReceiveMethod) => () => {
    setReceive(m);
    setStoreError(undefined);
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
        {member ? (
          <div className="rounded-sm border border-fg p-4 text-sm" data-testid="member-card">
            <p className="font-bold">ログイン中: {member.name} 様</p>
            <p className="mt-1 text-xs text-fg-muted">氏名・メールを会員情報から入れています（変更できます）</p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col justify-between gap-3 rounded-sm border border-fg-muted p-4 text-sm" data-testid="member-login-card">
              <div>
                <p className="font-bold">会員の方</p>
                <p className="mt-1 text-xs text-fg-muted">ログインしてご購入</p>
              </div>
              <Link href="/login?next=/checkout" className={buttonClass({ variant: "secondary", size: "md" })}>
                ログイン
              </Link>
            </div>
            <RadioCard name="who" value="guest" checked title="ゲストで購入" description="登録せずに進む" onChange={() => undefined} />
          </div>
        )}
      </section>

      {/* 受け取り方法 */}
      <section aria-labelledby="receive-heading" className="space-y-3">
        <h2 id="receive-heading" className={SECTION_TITLE}>
          受け取り方法
        </h2>
        <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-labelledby="receive-heading">
          <RadioCard
            name="receive"
            value="delivery"
            checked={!isStore}
            title="配送"
            description="ご指定のお届け先へお送りします"
            onChange={onSelectReceive("delivery")}
          />
          <RadioCard
            name="receive"
            value="store"
            checked={isStore}
            disabled={!storesAvailable}
            title="店舗受け取り"
            description={storesAvailable ? "お近くの店舗で受け取れます（送料はかかりません）" : "現在、受け取り店舗の一覧を取得できないため選べません"}
            onChange={onSelectReceive("store")}
          />
        </div>
        {!storesAvailable && (
          <p role="note" className="text-xs text-fg-muted" data-testid="stores-unavailable">
            店舗受け取りは現在ご利用いただけません。時間をおいて再読み込みしてください。
          </p>
        )}
        {isStore && storesAvailable && (
          <SelectField
            id="ship-store"
            label="受け取り店舗"
            required
            value={storeCode}
            onChange={(e) => {
              setStoreCode(e.target.value);
              setStoreError(undefined);
            }}
            error={storeError}
          >
            <option value="">選択してください</option>
            {stores.map((st) => (
              <option key={st.code} value={st.code}>
                {st.name}（{st.prefecture} {st.address}）
              </option>
            ))}
          </SelectField>
        )}
      </section>

      {/* お届け先／受け取る方 */}
      <section aria-labelledby="ship-heading" className="space-y-4">
        <h2 id="ship-heading" className={SECTION_TITLE}>
          {isStore ? "受け取る方" : "お届け先"}
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
        {!isStore && (
          <>
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
          </>
        )}
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
