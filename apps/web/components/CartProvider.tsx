"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchCart } from "@/lib/client/cart-api";
import type { Cart } from "@/lib/types";

/**
 * カート点数の共有状態（設計仕様書 6.2・テスト UT-WEB-01）。
 * - `itemCount` をヘッダーのバッジに渡す
 * - マウント時に `GET /api/cart` で取得する。ただし `hasCartCookie=false`（Cookie 無し＝カート未作成）のときは
 *   呼ばず 0 のまま。カート作成は最初の追加操作に任せる（サーバー側の判断を層で受ける）
 * - 変更 API の応答（カート応答）を `applyCart` に渡すと点数が更新される
 */

interface CartContextValue {
  itemCount: number;
  /** カート応答から点数を反映する */
  applyCart: (cart: Pick<Cart, "item_count">) => void;
  /** GET /api/cart を呼び直す（失敗は無視して現状維持） */
  refresh: () => Promise<void>;
}

const CartContext = createContext<CartContextValue | null>(null);

export function useCart(): CartContextValue {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart は CartProvider の内側で使ってください");
  return ctx;
}

export interface CartProviderProps {
  children: ReactNode;
  /** サーバーが Cookie `cart_token` を見て渡す。false ならマウント時の取得を省く */
  hasCartCookie?: boolean;
  /** テスト・SSR 用の初期値 */
  initialCount?: number;
}

export function CartProvider({ children, hasCartCookie = true, initialCount = 0 }: CartProviderProps) {
  const [itemCount, setItemCount] = useState(initialCount);

  const applyCart = useCallback((cart: Pick<Cart, "item_count">) => {
    setItemCount(Math.max(0, Math.trunc(cart.item_count ?? 0)));
  }, []);

  const refresh = useCallback(async () => {
    try {
      applyCart(await fetchCart());
    } catch {
      // 未接続・エラー時はバッジを更新しない（失敗の詳細はコンソールに出さない）
    }
  }, [applyCart]);

  useEffect(() => {
    if (!hasCartCookie) return;
    let cancelled = false;
    // 外部（BFF）からの応答が届いたコールバックで setState する。アンマウント後は反映しない
    fetchCart()
      .then((cart) => {
        if (!cancelled) applyCart(cart);
      })
      .catch(() => {
        // 未接続・エラー時はバッジを更新しない
      });
    return () => {
      cancelled = true;
    };
  }, [hasCartCookie, applyCart]);

  const value = useMemo(() => ({ itemCount, applyCart, refresh }), [itemCount, applyCart, refresh]);
  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}
