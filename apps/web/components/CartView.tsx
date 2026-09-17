"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useCart } from "@/components/CartProvider";
import ConfirmDialog from "@/components/ConfirmDialog";
import Price from "@/components/Price";
import { useToast } from "@/components/Toast";
import { cartErrorMessage, stockWarning } from "@/lib/cart-messages";
import { CartApiError, deleteCartItem, fetchCart, updateCartItem } from "@/lib/client/cart-api";
import { formatNumber } from "@/lib/format";
import { imageUrl } from "@/lib/image";
import { MAX_QUANTITY_PER_ITEM, type Cart, type CartItem } from "@/lib/types";

/**
 * カート画面本体（設計仕様書 6.6・DS-PRC-036、テスト AT-04・ST-F009-01/05）。
 * - 初期表示はサーバーが取得したカート（Cookie 無しなら null＝空）。`refetchOnMount` なら GET /api/cart で取り直す
 * - 数量変更は即時 PATCH、削除は確認ダイアログ → DELETE。処理中は該当明細のボタンを無効化＋処理中表示
 * - 応答のカートで全体（明細・小計・送料・合計・can_checkout・バッジ）を置き換える
 */

export interface CartViewProps {
  initialCart: Cart | null;
  imageBaseUrl: string;
  /** サーバー取得に失敗した（FastAPI 停止など）ときは true にして、クライアントで取り直す */
  refetchOnMount?: boolean;
  /** 送料無料の閾値。カート応答にも入るが空カートの表示に使う */
  freeShippingThreshold: number;
}

export default function CartView({ initialCart, imageBaseUrl, refetchOnMount = false, freeShippingThreshold }: CartViewProps) {
  const [cart, setCart] = useState<Cart | null>(initialCart);
  const [busyItem, setBusyItem] = useState<number | null>(null);
  const [pendingDelete, setPendingDelete] = useState<CartItem | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const { applyCart } = useCart();
  const toast = useToast();

  useEffect(() => {
    if (!refetchOnMount) return;
    fetchCart()
      .then((c) => {
        setCart(c);
        applyCart(c);
      })
      .catch(() => setLoadFailed(true));
  }, [refetchOnMount, applyCart]);

  const apply = (next: Cart) => {
    setCart(next);
    applyCart(next);
  };

  const handleError = (err: unknown) => {
    const status = err instanceof CartApiError ? err.status : 0;
    const body = err instanceof CartApiError ? err.body : null;
    toast.show({ kind: "error", message: cartErrorMessage(status, body) });
  };

  const onQuantityChange = async (item: CartItem, quantity: number) => {
    if (quantity === item.quantity) return;
    setBusyItem(item.item_id);
    try {
      apply(await updateCartItem(item.item_id, quantity));
      toast.show({ kind: "success", message: "数量を変更しました", durationMs: 2500 });
    } catch (err) {
      handleError(err);
    } finally {
      setBusyItem(null);
    }
  };

  const onConfirmDelete = async () => {
    if (!pendingDelete) return;
    const target = pendingDelete;
    setBusyItem(target.item_id);
    try {
      apply(await deleteCartItem(target.item_id));
      setPendingDelete(null);
      toast.show({ kind: "success", message: `${target.product_name} を削除しました` });
    } catch (err) {
      setPendingDelete(null);
      handleError(err);
    } finally {
      setBusyItem(null);
    }
  };

  const items = cart?.items ?? [];
  const count = cart?.item_count ?? 0;
  const threshold = cart?.free_shipping_threshold ?? freeShippingThreshold;
  const heading = (
    <h1 className="text-xl font-bold">
      カート{count > 0 && <span className="ml-2 text-base font-normal text-gray-700">（{count} 点）</span>}
    </h1>
  );

  if (loadFailed) {
    return (
      <div className="space-y-6">
        {heading}
        <div role="alert" className="rounded-lg border border-gray-300 bg-gray-50 p-6 text-center text-sm text-gray-700">
          カートを読み込めませんでした。時間をおいて再読み込みしてください。
        </div>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="space-y-6">
        {heading}
        <div className="py-12 text-center">
          <p className="text-sm text-gray-700">カートに商品が入っていません</p>
          <Link
            href="/"
            className="mt-4 inline-flex h-11 items-center rounded-md border border-gray-900 px-6 text-sm font-bold hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
          >
            買い物を続ける
          </Link>
        </div>
      </div>
    );
  }

  const canCheckout = cart?.can_checkout ?? false;

  return (
    <div className="space-y-6">
      {heading}
      <div className="grid gap-8 lg:grid-cols-[1fr_320px]">
      <ul className="divide-y divide-gray-200" aria-label="カートの商品">
        {items.map((item) => {
          const warning = stockWarning(item.stock_status);
          const busy = busyItem === item.item_id;
          return (
            <li key={item.item_id} className="flex gap-3 py-4" data-testid="cart-item">
              <Link href={`/products/${item.product_id}`} className="block w-24 shrink-0 sm:w-28">
                {/* eslint-disable-next-line @next/next/no-img-element -- プレースホルダー PNG を素直に表示 */}
                <img
                  src={imageUrl(imageBaseUrl, item.image_path) ?? undefined}
                  alt={item.product_name}
                  className="aspect-[3/4] w-full rounded-md bg-gray-100 object-cover"
                />
              </Link>
              <div className="min-w-0 flex-1 text-sm">
                <Link href={`/products/${item.product_id}`} className="font-medium hover:underline">
                  {item.product_name}
                </Link>
                <p className="mt-0.5 text-gray-600">
                  {item.color} / {item.size}
                </p>
                <p className="mt-1">
                  単価 <Price amount={item.unit_price} />
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <label className="flex items-center gap-2">
                    <span>数量</span>
                    <select
                      value={item.quantity}
                      disabled={busy}
                      onChange={(e) => onQuantityChange(item, Number(e.target.value))}
                      aria-label={`${item.product_name} の数量`}
                      className="h-9 rounded-md border border-gray-300 bg-white px-2 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
                    >
                      {Array.from({ length: MAX_QUANTITY_PER_ITEM }, (_, i) => i + 1).map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    disabled={busy}
                    aria-busy={busy}
                    onClick={() => setPendingDelete(item)}
                    aria-label={`${item.product_name} を削除`}
                    className="h-9 rounded-md border border-gray-300 px-3 text-sm hover:bg-gray-50 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
                  >
                    {busy ? "処理中…" : "削除"}
                  </button>
                  <span className="ml-auto font-bold">
                    小計 <Price amount={item.line_total} />
                  </span>
                </div>
                {warning && (
                  <p role="alert" className="mt-2 text-sm font-bold text-red-700">
                    ⚠ {warning}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <aside className="h-fit rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm lg:sticky lg:top-20" aria-label="金額">
        <dl className="space-y-2">
          <div className="flex justify-between">
            <dt>小計</dt>
            <dd>
              <Price amount={cart?.subtotal ?? 0} />
            </dd>
          </div>
          <div className="flex justify-between">
            <dt>
              送料 <span className="text-xs text-gray-600">（{formatNumber(threshold)} 円以上で無料）</span>
            </dt>
            <dd>{(cart?.shipping_fee ?? 0) === 0 ? "無料" : <Price amount={cart?.shipping_fee ?? 0} />}</dd>
          </div>
          <div className="flex justify-between border-t border-gray-300 pt-2 text-base font-bold">
            <dt>合計</dt>
            <dd>
              <Price amount={cart?.total ?? 0} taxNote />
            </dd>
          </div>
        </dl>
        {!canCheckout && (
          <p role="alert" className="mt-3 text-xs text-red-700">
            在庫切れ・在庫不足の商品があるためレジへ進めません
          </p>
        )}
        {canCheckout ? (
          <Link
            href="/checkout"
            className="mt-4 flex h-12 w-full items-center justify-center rounded-md bg-gray-900 text-sm font-bold text-white hover:bg-gray-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
          >
            レジへ進む
          </Link>
        ) : (
          <button
            type="button"
            disabled
            aria-disabled="true"
            className="mt-4 h-12 w-full rounded-md bg-gray-300 text-sm font-bold text-gray-600"
          >
            レジへ進む
          </button>
        )}
      </aside>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="商品を削除しますか？"
        description={pendingDelete ? `${pendingDelete.product_name}（${pendingDelete.color} / ${pendingDelete.size}）をカートから削除します。` : undefined}
        confirmLabel="削除する"
        destructive
        busy={pendingDelete !== null && busyItem === pendingDelete.item_id}
        onConfirm={onConfirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
      </div>
    </div>
  );
}
