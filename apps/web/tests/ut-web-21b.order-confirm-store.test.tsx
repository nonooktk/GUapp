import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CartProvider } from "@/components/CartProvider";
import OrderConfirm from "@/components/OrderConfirm";
import { ToastProvider } from "@/components/Toast";
import { CHECKOUT_KEY, LAST_ORDER_KEY, type CheckoutSession } from "@/lib/checkout-session";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";
import { makeOrder, STORE_PATCH } from "./helpers/fixtures";

// UT-WEB-21 の確認画面側（店舗受け取り）と IT-BFF-022 の送信本文の組み立て。設計仕様書 4.4・6.8・AT-15
const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace, refresh: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

const IDEM_KEY = "idemKey_-0123456789abcdefghijklmnopqrstuvwx"; // gitleaks:allow // pragma: allowlist secret

const storeSession: CheckoutSession = {
  form: { name: "受取 太郎", postal: "", prefecture: "", city: "", street: "", building: "", phone: "090-1234-5678", email: "pickup@example.com" },
  receive_method: "store",
  store_code: "demo-tokyo",
  store: { code: "demo-tokyo", name: "デモ店 東京", prefecture: "東京都", address: "千代田区デモ町1-2-3 デモビル1階" },
  prepare: {
    receive_method: "store",
    idempotency_key: IDEM_KEY,
    items: [
      { item_id: 1, variant_id: 3, product_id: 1, product_name: "テスト T シャツ", color: "黒", size: "M", unit_price: 1990, quantity: 2, line_total: 3980, stock_status: "ok", image_path: null },
    ],
    subtotal: 3980,
    shipping_fee: 0,
    total: 3980,
    tax_included: 361,
    tax_rate: "0.10",
    free_shipping_threshold: 4990,
  },
};

function renderConfirm() {
  return render(
    <ToastProvider>
      <CartProvider hasCartCookie={false} initialCount={2}>
        <OrderConfirm imageBaseUrl="http://localhost:3000" />
      </CartProvider>
    </ToastProvider>,
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.sessionStorage.setItem(CHECKOUT_KEY, JSON.stringify(storeSession));
  setCsrfCookie();
  push.mockReset();
  replace.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  clearCookies();
});

describe("店舗受け取りの確認画面", () => {
  it("受け取り方法の行に店舗名・住所、受け取る方、送料 ¥0 と注記を出す。郵便番号・お届け先は出さない", async () => {
    renderConfirm();
    await screen.findByText("ご注文内容の確認");
    const ship = screen.getByTestId("shipping-summary");
    expect(ship).toHaveTextContent("受け取る方");
    expect(ship).toHaveTextContent("受取 太郎 様");
    expect(ship).toHaveTextContent("店舗受け取り");
    expect(screen.getByTestId("store-info")).toHaveTextContent("デモ店 東京（東京都 千代田区デモ町1-2-3 デモビル1階）");
    expect(ship).not.toHaveTextContent("〒");
    expect(ship).not.toHaveTextContent("お届け先");
    const amounts = screen.getByTestId("amount-summary");
    expect(amounts).toHaveTextContent("送料");
    expect(amounts).toHaveTextContent("¥0");
    expect(screen.getByTestId("store-no-shipping-note")).toHaveTextContent("店舗受け取りのため送料はかかりません");
  });

  it("確定: receive_method=store・store_code・連絡先を送り、郵便番号・住所は送らない。完了画面へ", async () => {
    const { calls } = mockFetch(() => jsonResponse(201, makeOrder({ ...STORE_PATCH, ship_name: "受取 太郎" })));
    renderConfirm();
    await screen.findByText("ご注文内容の確認");
    fireEvent.click(screen.getByTestId("confirm-order"));
    fireEvent.click(screen.getByRole("button", { name: "確定する" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].url).toBe("/api/orders");
    expect(calls[0].body).toEqual({
      idempotency_key: IDEM_KEY,
      ship_name: "受取 太郎",
      ship_phone: "09012345678",
      guest_email: "pickup@example.com",
      receive_method: "store",
      store_code: "demo-tokyo",
      payment_method: "card",
      display: { subtotal: 3980, shipping_fee: 0, total: 3980 },
    });
    await act(async () => undefined);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/orders/complete?n=GU-261024-ABCDEFGH"));
    expect(JSON.parse(window.sessionStorage.getItem(LAST_ORDER_KEY) ?? "{}").pickup_code).toBe("ABCD2345");
  });

  it("409 invalid_reference（店舗が使えない）: 店舗受け取りの選択を残したまま /checkout へ戻す", async () => {
    mockFetch(() => jsonResponse(409, { code: "invalid_reference", field: "store_code" }));
    renderConfirm();
    await screen.findByText("ご注文内容の確認");
    fireEvent.click(screen.getByTestId("confirm-order"));
    fireEvent.click(screen.getByRole("button", { name: "確定する" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/checkout"));
    const saved = JSON.parse(window.sessionStorage.getItem(CHECKOUT_KEY) ?? "null") as CheckoutSession;
    expect(saved.prepare).toBeNull();
    expect(saved.receive_method).toBe("store");
    expect(saved.store_code).toBe("demo-tokyo");
  });
});
