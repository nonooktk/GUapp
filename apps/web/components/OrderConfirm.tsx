"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import Button, { buttonClass } from "@/components/Button";
import { useCart } from "@/components/CartProvider";
import ConfirmDialog from "@/components/ConfirmDialog";
import { AmountSummary, OrderItemsList, ShippingSummary } from "@/components/OrderSummary";
import { useToast } from "@/components/Toast";
import { mapServerFieldErrors, toShippingBody } from "@/lib/checkout-validation";
import { CHECKOUT_KEY, clearCheckoutSession, saveCheckoutSession, saveLastOrder, type CheckoutSession } from "@/lib/checkout-session";
import { parseJsonOrNull, useHydrated, useSessionItem } from "@/lib/client/use-session-item";
import { CartApiError } from "@/lib/client/cart-api";
import { createOrder } from "@/lib/client/order-api";
import { imageUrl } from "@/lib/image";
import { routeOrderError } from "@/lib/order-errors";
import type { OrderCreateBody } from "@/lib/types";

/**
 * 注文確認 DS-SCR-006（確認）（設計仕様書 6.8・DS-PRC-014-1・DS-PRC-036、テスト AT-01・AT-05・ST-F013-01・ST-F036-01・UT-WEB-02/03）。
 * - sessionStorage（guapp.checkout）から prepare 応答とフォーム値を復元。無ければ／prepare が捨てられていれば /checkout へ戻す
 * - 注文内容・お届け先・メール・受け取り／支払い方法・金額（小計・送料・合計・うち消費税）
 * - 「注文を確定する」→ ConfirmDialog → OK で busy（両ボタン無効・処理中…・再クリックで 2 回目の送信をしない）→ `POST /api/orders`
 *   `display` には表示中の 3 金額を入れ、FastAPI が再計算と照合する（price_changed）
 * - 成功（201／200）: 応答を guapp.lastOrder に保存、バッジ 0、guapp.checkout を削除、/orders/complete?n=… へ。トースト「ご注文ありがとうございます」
 * - 失敗: lib/order-errors.ts の戻し先。price_changed／payment_failed は prepare を捨てて SCR-005 へ（次に確認画面を開くとき prepare を呼び直す）
 */

export interface OrderConfirmProps {
  imageBaseUrl: string;
}

export default function OrderConfirm({ imageBaseUrl }: OrderConfirmProps) {
  const router = useRouter();
  const toast = useToast();
  const { applyCart } = useCart();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // クリックが連続しても送信は 1 回だけ（state の更新より先に立てる同期フラグ）
  const inflight = useRef(false);
  // 遷移を始めたら sessionStorage を消しても /checkout へ送り返さない
  const leaving = useRef(false);

  const hydrated = useHydrated();
  const raw = useSessionItem(CHECKOUT_KEY);
  const session = useMemo(() => {
    const v = parseJsonOrNull<CheckoutSession>(raw);
    return v && typeof v.form === "object" && v.form !== null ? v : null;
  }, [raw]);
  const prepare = session?.prepare ?? null;
  const loaded = hydrated;

  // 復元できない（直接開いた・prepare を捨てた後）なら SCR-005 へ
  useEffect(() => {
    if (hydrated && !leaving.current && !prepare) router.replace("/checkout");
  }, [hydrated, prepare, router]);

  const go = (href: string) => {
    leaving.current = true;
    router.push(href);
  };

  const submit = async () => {
    if (!session || !prepare || inflight.current) return;
    inflight.current = true;
    setBusy(true);

    const body: OrderCreateBody = {
      idempotency_key: prepare.idempotency_key,
      ...toShippingBody(session.form),
      receive_method: "delivery",
      payment_method: "card",
      display: { subtotal: prepare.subtotal, shipping_fee: prepare.shipping_fee, total: prepare.total },
    };

    try {
      const { data: order } = await createOrder(body);
      saveLastOrder(order);
      clearCheckoutSession();
      applyCart({ item_count: 0 });
      toast.show({ kind: "success", message: "ご注文ありがとうございます", durationMs: 6000 });
      go(`/orders/complete?n=${encodeURIComponent(order.order_number)}`);
      // 遷移するので busy は解かない（戻ってきたときは useEffect が /checkout へ送る）
    } catch (err) {
      const status = err instanceof CartApiError ? err.status : 0;
      const errBody = err instanceof CartApiError ? err.body : null;
      const route = routeOrderError(status, errBody);
      setDialogOpen(false);
      switch (route.kind) {
        case "field_errors":
          // フォーム値と項目エラーを持って SCR-005 へ。prepare（冪等キー）はそのまま使える
          saveCheckoutSession({
            form: session.form,
            prepare,
            serverErrors: mapServerFieldErrors(route.fields),
          });
          toast.show({ kind: "error", message: route.message });
          go("/checkout");
          break;
        case "cart": {
          clearCheckoutSession();
          toast.show({ kind: "error", message: route.message });
          const q = route.variantIds.length > 0 ? `?oos=${route.variantIds.join(",")}` : "";
          go(`/cart${q}`);
          break;
        }
        case "checkout":
          // prepare を捨てる → 次に「確認画面へ」を押すと新しい冪等キーで prepare を呼び直す
          saveCheckoutSession({ form: session.form, prepare: null, focus: route.focus });
          toast.show({ kind: "error", message: route.message });
          go("/checkout");
          break;
        case "complete":
          clearCheckoutSession();
          applyCart({ item_count: 0 });
          toast.show({ kind: "info", message: route.message });
          go(`/orders/complete?n=${encodeURIComponent(route.orderNumber)}`);
          break;
        case "stay":
        default:
          toast.show({ kind: "error", message: route.message });
          inflight.current = false;
          setBusy(false);
      }
    }
  };

  if (!loaded || !session || !prepare) {
    return (
      <p role="status" className="py-12 text-center text-sm text-fg-muted">
        読み込み中…
      </p>
    );
  }

  const shipping = toShippingBody(session.form);
  const items = prepare.items.map((it) => ({
    ...it,
    image_url: imageUrl(imageBaseUrl, it.image_path),
  }));

  return (
    <div className="space-y-8">
      <h1 className="text-xl font-light tracking-heading">ご注文内容の確認</h1>

      <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
        <div className="space-y-8">
          <section aria-labelledby="items-heading" className="space-y-2">
            <h2 id="items-heading" className="text-lg font-light tracking-heading">
              注文内容
            </h2>
            <OrderItemsList items={items} />
          </section>

          <section aria-labelledby="ship-heading" className="space-y-3">
            <div className="flex items-baseline justify-between">
              <h2 id="ship-heading" className="text-lg font-light tracking-heading">
                お届け先・お支払い
              </h2>
              <Link href="/checkout" className="text-sm underline underline-offset-2">
                変更する
              </Link>
            </div>
            <ShippingSummary {...shipping} receive_method="delivery" payment_method="card" />
          </section>
        </div>

        <div className="space-y-4 lg:sticky lg:top-20 lg:h-fit">
          <AmountSummary
            subtotal={prepare.subtotal}
            shipping_fee={prepare.shipping_fee}
            total={prepare.total}
            tax_included={prepare.tax_included}
            free_shipping_threshold={prepare.free_shipping_threshold}
          />
          {/* 冪等キーは hidden 相当としてクライアント状態に保持（画面には出さない） */}
          <input type="hidden" name="idempotency_key" value={prepare.idempotency_key} readOnly data-testid="idempotency-key" />
          <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
            {busy ? (
              <Button variant="secondary" size="lg" disabled className="sm:w-auto" data-testid="back-button">
                戻る
              </Button>
            ) : (
              <Link href="/checkout" className={buttonClass({ variant: "secondary", size: "lg" })} data-testid="back-button">
                戻る
              </Link>
            )}
            <Button
              variant="primary"
              size="lg"
              busy={busy}
              busyLabel="処理中…"
              onClick={() => setDialogOpen(true)}
              className="sm:flex-1"
              data-testid="confirm-order"
            >
              注文を確定する
            </Button>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={dialogOpen}
        title="ご注文を確定しますか？"
        description="この内容で注文を確定します。よろしいですか？"
        confirmLabel="確定する"
        busy={busy}
        onConfirm={submit}
        onCancel={() => !busy && setDialogOpen(false)}
      />
    </div>
  );
}
