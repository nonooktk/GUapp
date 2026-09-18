import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CartProvider } from "@/components/CartProvider";
import OrderConfirm from "@/components/OrderConfirm";
import { ToastProvider } from "@/components/Toast";
import { CHECKOUT_KEY, LAST_ORDER_KEY, type CheckoutSession } from "@/lib/checkout-session";
import type { OrderResponse } from "@/lib/types";

// テスト設計書 UT-WEB-02（確認ダイアログ。キャンセルで送信されない）・UT-WEB-03（送信中は両ボタン無効・処理中表示・再クリックで 2 回目の送信が起きない）
// 設計仕様書 6.8・DS-PRC-036・AT-05・ST-F036-01

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace, prefetch: vi.fn(), back: vi.fn() }),
}));

const CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret
const IDEM_KEY = "idemKey_-0123456789abcdefghijklmnopqrstuvwx"; // gitleaks:allow // pragma: allowlist secret

const session: CheckoutSession = {
  form: {
    name: "テスト 太郎",
    postal: "100-0001",
    prefecture: "東京都",
    city: "千代田区",
    street: "千代田1-1",
    building: "テストビル 101",
    phone: "090-1234-5678",
    email: "test@example.com",
  },
  prepare: {
    idempotency_key: IDEM_KEY,
    items: [
      {
        item_id: 1,
        variant_id: 3,
        product_id: 1,
        product_name: "テスト T シャツ",
        color: "黒",
        size: "M",
        unit_price: 1990,
        quantity: 2,
        line_total: 3980,
        stock_status: "ok",
        image_path: "products/001/1.jpg",
      },
    ],
    subtotal: 3980,
    shipping_fee: 550,
    total: 4530,
    tax_included: 411,
    tax_rate: "0.10",
    free_shipping_threshold: 4990,
  },
};

const orderOut: OrderResponse = {
  order_number: "GU-260918-7K3M9Q2X",
  status: "accepted",
  items: [{ product_name: "テスト T シャツ", color: "黒", size: "M", unit_price: 1990, quantity: 2, line_total: 3980 }],
  subtotal: 3980,
  shipping_fee: 550,
  total: 4530,
  tax_included: 411,
  tax_rate: "0.10",
  ship_name: "テスト 太郎",
  ship_postal_code: "1000001",
  ship_address: "東京都　千代田区　千代田1-1　テストビル 101",
  ship_phone: "09012345678",
  guest_email: "test@example.com",
  receive_method: "delivery",
  payment_method: "card",
  ordered_at: "2026-09-18T03:04:05Z",
};

const fetchMock = vi.fn();

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
  window.sessionStorage.setItem(CHECKOUT_KEY, JSON.stringify(session));
  // csrf_token Cookie を先に置き、ensureCsrfToken が GET /api/cart を呼ばないようにする（fetch 回数を送信だけにする）
  document.cookie = `csrf_token=${CSRF}; path=/`;
  vi.stubGlobal("fetch", fetchMock);
  push.mockReset();
  replace.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

const confirmButton = () => screen.getByTestId("confirm-order") as HTMLButtonElement;

describe("確認画面の表示（ST-F013-01）", () => {
  it("明細・金額（小計・送料・合計・うち消費税）・お届け先・メール・受け取り／支払い方法を表示する", async () => {
    renderConfirm();
    await screen.findByText("ご注文内容の確認");
    expect(screen.getByText("テスト T シャツ")).toBeInTheDocument();
    const amounts = screen.getByTestId("amount-summary");
    expect(amounts).toHaveTextContent("¥3,980");
    expect(amounts).toHaveTextContent("¥550");
    expect(amounts).toHaveTextContent("¥4,530");
    expect(amounts).toHaveTextContent("うち消費税");
    expect(amounts).toHaveTextContent("¥411");
    const ship = screen.getByTestId("shipping-summary");
    expect(ship).toHaveTextContent("テスト 太郎 様");
    expect(ship).toHaveTextContent("〒100-0001");
    // toHaveTextContent は空白を正規化する（全角スペースも半角 1 個になる）ので textContent を直接見る
    expect(ship.textContent).toContain("東京都　千代田区　千代田1-1　テストビル 101");
    expect(ship).toHaveTextContent("test@example.com");
    expect(ship).toHaveTextContent("配送");
    expect(ship).toHaveTextContent("クレジットカード（テスト決済）");
    expect(screen.getByTestId("idempotency-key")).toHaveValue(IDEM_KEY);
  });

  it("sessionStorage に prepare が無ければ /checkout へ戻す", async () => {
    window.sessionStorage.setItem(CHECKOUT_KEY, JSON.stringify({ ...session, prepare: null }));
    renderConfirm();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/checkout"));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("UT-WEB-02 確認ダイアログ", () => {
  it("「注文を確定する」クリックでダイアログ表示、キャンセルで fetch は呼ばれない", async () => {
    renderConfirm();
    await screen.findByText("ご注文内容の確認");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(confirmButton());
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("この内容で注文を確定します。よろしいですか？");

    fireEvent.click(screen.getByRole("button", { name: "キャンセル" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });
});

describe("UT-WEB-03 処理中表示・二重送信防止", () => {
  it("送信中は両ボタン disabled・「処理中…」。確定を連続 2 回クリックしても fetch は 1 回。display は表示中の 3 金額", async () => {
    let resolveFetch: (r: Response) => void = () => undefined;
    fetchMock.mockImplementation(() => new Promise<Response>((r) => (resolveFetch = r)));

    renderConfirm();
    await screen.findByText("ご注文内容の確認");
    fireEvent.click(confirmButton());
    const ok = screen.getByRole("button", { name: "確定する" });

    // 連続 2 回クリック
    fireEvent.click(ok);
    fireEvent.click(ok);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    // 画面のボタンは両方無効・処理中表示
    expect(confirmButton()).toBeDisabled();
    expect(confirmButton()).toHaveTextContent("処理中…");
    expect(confirmButton()).toHaveAttribute("aria-busy", "true");
    expect(screen.getByTestId("back-button")).toBeDisabled();
    // ダイアログ側のボタン（確定する→処理中…、キャンセル）も無効
    const busyButtons = screen.getAllByRole("button", { name: "処理中…" });
    expect(busyButtons).toHaveLength(2); // 画面の「注文を確定する」＋ダイアログの「確定する」
    for (const b of busyButtons) expect(b).toBeDisabled();
    expect(screen.getByRole("button", { name: "キャンセル" })).toBeDisabled();

    // さらに押しても増えない
    fireEvent.click(confirmButton());
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/orders");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe(CSRF);
    const body = JSON.parse(init.body as string);
    expect(body).toMatchObject({
      idempotency_key: IDEM_KEY,
      ship_name: "テスト 太郎",
      ship_postal_code: "1000001",
      ship_address: "東京都　千代田区　千代田1-1　テストビル 101",
      ship_phone: "09012345678",
      guest_email: "test@example.com",
      receive_method: "delivery",
      payment_method: "card",
      display: { subtotal: 3980, shipping_fee: 550, total: 4530 },
    });

    // 201 → lastOrder 保存・checkout 削除・完了画面へ
    await act(async () => {
      resolveFetch(new Response(JSON.stringify(orderOut), { status: 201, headers: { "Content-Type": "application/json" } }));
    });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/orders/complete?n=GU-260918-7K3M9Q2X"));
    expect(JSON.parse(window.sessionStorage.getItem(LAST_ORDER_KEY) ?? "null")).toMatchObject({ order_number: "GU-260918-7K3M9Q2X" });
    expect(window.sessionStorage.getItem(CHECKOUT_KEY)).toBeNull();
    expect(screen.getByTestId("toast")).toHaveTextContent("ご注文ありがとうございます");
  });

  it("409 price_changed → prepare を捨てて /checkout へ（次に確認画面を開くとき prepare を呼び直す）", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ code: "price_changed", amounts: { subtotal: 1, shipping_fee: 2, total: 3 } }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );
    renderConfirm();
    await screen.findByText("ご注文内容の確認");
    fireEvent.click(confirmButton());
    fireEvent.click(screen.getByRole("button", { name: "確定する" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/checkout"));
    const saved = JSON.parse(window.sessionStorage.getItem(CHECKOUT_KEY) ?? "null") as CheckoutSession;
    expect(saved.prepare).toBeNull();
    expect(saved.form.name).toBe("テスト 太郎");
    expect(screen.getByTestId("toast")).toHaveTextContent("金額が変わりました");
  });

  it("409 out_of_stock → /cart?oos=… へ、トースト「在庫切れの商品があります」", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ code: "out_of_stock", items: [3] }), { status: 409, headers: { "Content-Type": "application/json" } }),
    );
    renderConfirm();
    await screen.findByText("ご注文内容の確認");
    fireEvent.click(confirmButton());
    fireEvent.click(screen.getByRole("button", { name: "確定する" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/cart?oos=3"));
    expect(screen.getByTestId("toast")).toHaveTextContent("在庫切れの商品があります");
  });

  it("503（接続不可）→ その場に留まり、ボタンが再び押せる", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ code: "upstream_unavailable" }), { status: 503, headers: { "Content-Type": "application/json" } }),
    );
    renderConfirm();
    await screen.findByText("ご注文内容の確認");
    fireEvent.click(confirmButton());
    fireEvent.click(screen.getByRole("button", { name: "確定する" }));
    await waitFor(() => expect(screen.getByTestId("toast")).toHaveTextContent("サーバーに接続できません"));
    expect(push).not.toHaveBeenCalled();
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    expect(confirmButton()).toHaveTextContent("注文を確定する");
  });
});
