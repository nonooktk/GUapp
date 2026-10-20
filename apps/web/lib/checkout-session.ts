import type { CheckoutErrors, CheckoutFormValues } from "@/lib/checkout-validation";
import type { OrderResponse, PrepareResponse, ReceiveMethod, StoreSummary } from "@/lib/types";

/**
 * 注文手続きの画面間で持ち回る状態を `sessionStorage` に置く（DS-SCR-005 → 006）。
 * - `guapp.checkout`: フォーム値 ＋ prepare 応答（冪等キー・金額）。price_changed／payment_failed のときは prepare を捨てて
 *   フォーム値だけ残し、確認画面を開き直すときに prepare を呼び直させる
 * - `guapp.lastOrder`: 確定した注文応答。完了画面の再掲に使う（無ければ照会フォーム）
 * 個人情報（配送先・メール）はタブを閉じれば消える sessionStorage に限定し、localStorage には置かない。
 * 読み書きは try/catch で包み、使えない環境（プライベートモード等）でも画面が落ちないようにする。
 * 読み出しは lib/client/use-session-item.ts のフック（useSyncExternalStore）で行う。
 */

export const CHECKOUT_KEY = "guapp.checkout";
export const LAST_ORDER_KEY = "guapp.lastOrder";

export interface CheckoutSession {
  /** 店舗受け取りのときは郵便番号・住所の欄を空にして保存する（送信しない値を残さない）。復元は lib/checkout-validation の ADDRESS_FIELDS */
  form: CheckoutFormValues;
  /** P2-b: 受け取り方法。無ければ配送（古い保存値） */
  receive_method?: ReceiveMethod;
  /** P2-b: 店舗受け取りの店舗コードと表示用の店舗情報（確認画面は店舗一覧を取得しないため、名前・住所を持ち回る） */
  store_code?: string;
  store?: StoreSummary;
  /** 確認画面の元データ。null なら SCR-005 からやり直す */
  prepare: PrepareResponse | null;
  /** サーバーの 400 を SCR-005 に持ち帰るときの項目エラー */
  serverErrors?: CheckoutErrors;
  /** payment_failed で戻ったときに支払い方法へフォーカスさせる */
  focus?: "form" | "payment";
}

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown): void {
  const s = storage();
  if (!s) return;
  try {
    s.setItem(key, JSON.stringify(value));
  } catch {
    // 容量超過・無効化時は諦める（画面側は復元できなければ SCR-005 に戻す）
  }
}

function remove(key: string): void {
  const s = storage();
  if (!s) return;
  try {
    s.removeItem(key);
  } catch {
    // 無視
  }
}

export function saveCheckoutSession(session: CheckoutSession): void {
  write(CHECKOUT_KEY, session);
}

export function clearCheckoutSession(): void {
  remove(CHECKOUT_KEY);
}

export function saveLastOrder(order: OrderResponse): void {
  write(LAST_ORDER_KEY, order);
}

/** 画面間で持ち回る受け取り方法の項目だけを取り出す（serverErrors・focus を消して保存し直すときに使う） */
export function carryReceive(session: CheckoutSession): Pick<CheckoutSession, "receive_method" | "store_code" | "store"> {
  return { receive_method: session.receive_method, store_code: session.store_code, store: session.store };
}
