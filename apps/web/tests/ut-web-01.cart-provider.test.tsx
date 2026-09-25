import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CartProvider, useCart } from "@/components/CartProvider";
import HeaderWithCart from "@/components/HeaderWithCart";
import type { Cart } from "@/lib/types";

// テスト設計書 UT-WEB-01: カート追加のレスポンス（item_count）でヘッダーのバッジが更新される
// Header は P2-a の SearchBox（useRouter）を内部で使うため、App Router 無しで render するにはモックが要る
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));
function cartResponse(itemCount: number): Cart {
  return {
    cart_token: "tok",
    items: [],
    item_count: itemCount,
    subtotal: 0,
    shipping_fee: 0,
    total: 0,
    free_shipping_threshold: 4990,
    can_checkout: false,
  };
}

/** 追加 API の応答を applyCart に渡す役（PurchasePanel の代わり） */
function ApplyButton({ response }: { response: Cart }) {
  const { applyCart } = useCart();
  return (
    <button type="button" onClick={() => applyCart(response)}>
      apply
    </button>
  );
}

describe("UT-WEB-01 CartProvider → Header バッジ", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("追加 API の応答（item_count: 3）を applyCart に渡すとバッジが 3 になる", async () => {
    render(
      <CartProvider hasCartCookie={false}>
        <HeaderWithCart />
        <ApplyButton response={cartResponse(3)} />
      </CartProvider>,
    );
    expect(screen.queryByTestId("cart-count-badge")).not.toBeInTheDocument();

    await act(async () => {
      screen.getByRole("button", { name: "apply" }).click();
    });

    expect(screen.getByTestId("cart-count-badge")).toHaveTextContent("3");
    expect(screen.getByRole("link", { name: "カート（3点）" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled(); // Cookie 無しではマウント時に GET /api/cart を呼ばない
  });

  it("Cookie ありならマウント時に GET /api/cart を呼び、応答の item_count をバッジに出す", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(cartResponse(5)), { status: 200 }));
    render(
      <CartProvider hasCartCookie>
        <HeaderWithCart />
      </CartProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("cart-count-badge")).toHaveTextContent("5"));
    expect(fetchMock).toHaveBeenCalledWith("/api/cart", expect.objectContaining({ method: "GET" }));
  });

  it("GET /api/cart が失敗してもバッジは 0（非表示）のまま", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ code: "upstream_unavailable" }), { status: 503 }));
    render(
      <CartProvider hasCartCookie>
        <HeaderWithCart />
      </CartProvider>,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByTestId("cart-count-badge")).not.toBeInTheDocument();
  });
});
