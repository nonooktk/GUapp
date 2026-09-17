"use client";

import { useState } from "react";
import { useCart } from "@/components/CartProvider";
import Price from "@/components/Price";
import { useToast } from "@/components/Toast";
import { cartErrorMessage } from "@/lib/cart-messages";
import { addCartItem, CartApiError } from "@/lib/client/cart-api";
import { MAX_QUANTITY_PER_ITEM, type Variant } from "@/lib/types";

/**
 * 商品詳細の購入操作（設計仕様書 6.5・U-05・REQ-FR-1203、テスト UT-WEB-07/08・AT-03・ST-F005-02/03）。
 * - 色・サイズはボタン（`aria-pressed`）、数量はセレクト（1〜10）
 * - 選択中の組合せを `variants[]` から解決。無い／`in_stock=false` なら「在庫切れ」＋追加ボタン無効
 * - 375px では下部固定バー（選択内容・価格・追加ボタン）。sm 以上ではパネル内のボタンだけ表示
 * - 追加成功: トースト＋バッジ更新＋「カートを見る」導線。409／422 は文言を出し分け
 */

export interface PurchasePanelProps {
  productId: number;
  price: number;
  colors: string[];
  sizes: string[];
  variants: Variant[];
}

/** 色・サイズから variant を解決する（純粋関数。UT-WEB-08 で直接検証） */
export function resolveVariant(variants: Variant[], color: string | null, size: string | null): Variant | null {
  if (color === null || size === null) return null;
  return variants.find((v) => v.color === color && v.size === size) ?? null;
}

const chipBase =
  "h-10 min-w-12 rounded-md border px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900";
const chipOn = "border-gray-900 bg-gray-900 text-white";
const chipOff = "border-gray-300 bg-white text-gray-900 hover:bg-gray-50";

export default function PurchasePanel({ productId, price, colors, sizes, variants }: PurchasePanelProps) {
  const [color, setColor] = useState<string | null>(colors.length === 1 ? colors[0] : null);
  const [size, setSize] = useState<string | null>(sizes.length === 1 ? sizes[0] : null);
  const [quantity, setQuantity] = useState(1);
  const [busy, setBusy] = useState(false);
  const { applyCart } = useCart();
  const toast = useToast();

  const variant = resolveVariant(variants, color, size);
  const selected = color !== null && size !== null;
  const outOfStock = selected && (variant === null || !variant.in_stock);
  const canAdd = selected && variant !== null && variant.in_stock && !busy;

  /** 色だけ選んだ段階で、その色に在庫のあるサイズが 1 つも無いかなど、チップ側の補助表示に使う */
  const isCombinationOut = (c: string | null, s: string | null) => {
    if (c === null || s === null) return false;
    const v = resolveVariant(variants, c, s);
    return v === null || !v.in_stock;
  };

  const onAdd = async () => {
    if (!variant || !canAdd) return;
    setBusy(true);
    try {
      const cart = await addCartItem(variant.variant_id, quantity);
      applyCart(cart);
      toast.show({
        kind: "success",
        message: `カートに追加しました（${color} / ${size} × ${quantity}）`,
        action: { label: "カートを見る", href: "/cart" },
        durationMs: 6000,
      });
    } catch (err) {
      const status = err instanceof CartApiError ? err.status : 0;
      const body = err instanceof CartApiError ? err.body : null;
      toast.show({ kind: "error", message: cartErrorMessage(status, body) });
    } finally {
      setBusy(false);
    }
  };

  const stockLabel = !selected ? "色とサイズを選択してください" : outOfStock ? "在庫切れ" : "在庫あり";

  const addButton = (extra = "") => (
    <button
      type="button"
      onClick={onAdd}
      disabled={!canAdd}
      aria-busy={busy}
      aria-label={outOfStock ? "在庫切れのため追加できません" : "カートに入れる"}
      data-testid="add-to-cart"
      className={`h-12 rounded-md bg-gray-900 px-6 text-sm font-bold text-white hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900 ${extra}`}
    >
      {busy ? "追加中…" : outOfStock ? "在庫切れ" : "カートに入れる"}
    </button>
  );

  return (
    <div className="space-y-5" data-product-id={productId}>
      {/* 色 */}
      <fieldset>
        <legend className="mb-2 text-sm font-bold">
          色{color && <span className="ml-2 font-normal text-gray-700">{color}</span>}
        </legend>
        <div className="flex flex-wrap gap-2" role="group" aria-label="色を選択">
          {colors.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setColor(c)}
              aria-pressed={color === c}
              aria-label={`色 ${c}${isCombinationOut(c, size) ? "（在庫切れ）" : ""}`}
              className={`${chipBase} ${color === c ? chipOn : chipOff} ${isCombinationOut(c, size) ? "line-through opacity-70" : ""}`}
            >
              {c}
            </button>
          ))}
        </div>
      </fieldset>

      {/* サイズ */}
      <fieldset>
        <legend className="mb-2 text-sm font-bold">
          サイズ{size && <span className="ml-2 font-normal text-gray-700">{size}</span>}
        </legend>
        <div className="flex flex-wrap gap-2" role="group" aria-label="サイズを選択">
          {sizes.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSize(s)}
              aria-pressed={size === s}
              aria-label={`サイズ ${s}${isCombinationOut(color, s) ? "（在庫切れ）" : ""}`}
              className={`${chipBase} ${size === s ? chipOn : chipOff} ${isCombinationOut(color, s) ? "line-through opacity-70" : ""}`}
            >
              {s}
            </button>
          ))}
        </div>
      </fieldset>

      {/* 在庫表示＋数量 */}
      <div className="flex flex-wrap items-center gap-4">
        <p data-testid="stock-status" className={`text-sm font-bold ${outOfStock ? "text-red-700" : "text-gray-700"}`} aria-live="polite">
          {stockLabel}
        </p>
        <label className="flex items-center gap-2 text-sm">
          <span className="font-bold">数量</span>
          <select
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
            aria-label="数量"
            className="h-10 rounded-md border border-gray-300 bg-white px-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-900"
          >
            {Array.from({ length: MAX_QUANTITY_PER_ITEM }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* パネル内ボタン（sm 以上） */}
      <div className="hidden sm:block">{addButton("w-full sm:w-auto")}</div>

      {/* 375px 下部固定バー（ST-F005-03）。本文の末尾に隠れないよう page 側で pb を確保する */}
      <div
        data-testid="sticky-bar"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-gray-200 bg-white/95 px-4 py-3 backdrop-blur sm:hidden"
      >
        <div className="mx-auto flex max-w-screen-xl items-center justify-between gap-3">
          <div className="min-w-0 text-sm">
            <p className="truncate text-gray-700">
              {color ?? "色未選択"} / {size ?? "サイズ未選択"} / {quantity}
            </p>
            <Price amount={price * quantity} className="font-bold" />
          </div>
          {addButton("shrink-0")}
        </div>
      </div>
    </div>
  );
}
