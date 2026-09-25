import type { CheckoutFormValues } from "@/lib/checkout-validation";

/**
 * 注文手続きフォーム（DS-SCR-005）の初期値に入れるダミー値と注意書き（設計仕様書 P2 追補a 9.1 DS-DEC-47）。
 * - 目的: 講義の Azure MySQL（ADR-0002・guapp_nonooktk）や、開発サーバー越しに利用者が誤って
 *   本物の氏名・住所・電話番号・メールアドレスを入力してしまう事故を防ぐ。
 * - `CheckoutForm.tsx` は sessionStorage（`guapp.checkout`）に復元値が無いときだけこの値を初期値にする。
 *   確認画面から戻ってきたとき（利用者が一度入力した値がある場合）は復元値を優先し、このダミー値では上書きしない。
 * - 値はすべて架空（実在の個人・企業ではない）。クライアント（`checkout-validation.ts`）・
 *   サーバー（`apps/api/app/schemas/order.py`）双方の入力検証をそのまま通る形式にしてある
 *   （郵便番号・電話は半角数字、メールは `example.com`＝RFC 2606 で例示用に予約されたドメイン）。
 * - 本番（P2-d で Azure App Service に公開）でも同じデモサイトとして運用するため、
 *   この初期値と注意書きは環境で出し分けず常時表示する（DS-DEC-47）。
 */

export const DEMO_CHECKOUT_FORM: CheckoutFormValues = {
  name: "デモ 太郎",
  postal: "000-0000",
  prefecture: "東京都",
  city: "千代田区",
  street: "デモ町1-2-3",
  building: "サンプルビル101",
  phone: "090-0000-0000",
  email: "demo@example.com",
};

export const DEMO_NOTICE_TITLE = "講義演習用のデモサイトです";
export const DEMO_NOTICE_BODY =
  "入力欄にはダミーの値が入っています。実際の氏名・住所・電話番号・メールアドレスは入力しないでください。";
