import { useSyncExternalStore } from "react";

/**
 * `sessionStorage` の 1 キーを読むフック（注文手続きの画面間受け渡し用）。
 * - `useSyncExternalStore` を使い、サーバー描画・ハイドレーション中は null、その後にクライアントの値で描き直す
 *   （useEffect 内で setState する書き方は react-hooks/set-state-in-effect に引っかかり、useState 初期化子だと SSR と食い違う）
 * - 同一タブ内で他から書き換わることは想定しないので購読は空。値は文字列なので比較は値で安定する
 * - `useHydrated` は「まだサーバー値を描いている段階か」を知るため（未ハイドレーションで「無い」と決めないように）
 */

const noopSubscribe = () => () => {};

function readItem(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export function useSessionItem(key: string): string | null {
  return useSyncExternalStore(
    noopSubscribe,
    () => readItem(key),
    () => null,
  );
}

export function useHydrated(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}

/** JSON 文字列を安全に parse。壊れていれば null */
export function parseJsonOrNull<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}
