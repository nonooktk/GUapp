import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import OrderComplete from "@/components/OrderComplete";
import { LAST_ORDER_KEY } from "@/lib/checkout-session";
import { formatPickupCode, formatStoreAddress } from "@/lib/format";
import { makeOrder, STORE_PATCH } from "./helpers/fixtures";

// テスト設計書 UT-WEB-21（注文完了の受け取りコード。DS-SCR-006）。設計仕様書 6.8・DS-PRC-014-3・AT-15
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

beforeEach(() => window.sessionStorage.clear());
afterEach(() => window.sessionStorage.clear());

function renderComplete(order = makeOrder()) {
  window.sessionStorage.setItem(LAST_ORDER_KEY, JSON.stringify(order));
  return render(<OrderComplete orderNumber={order.order_number} />);
}

describe("UT-WEB-21 注文完了の受け取りコード", () => {
  it("formatPickupCode: 8 文字を 4 文字ずつハイフンで区切る。8 文字でない値はそのまま", () => {
    expect(formatPickupCode("ABCD2345")).toBe("ABCD-2345");
    expect(formatPickupCode("ABC")).toBe("ABC");
    expect(formatPickupCode("ABCD-2345")).toBe("ABCD-2345");
  });

  it("formatStoreAddress: API の住所が都道府県から始まるなら重ねない（seed は「東京都千代田区…」）。始まらなければ前に付ける", () => {
    expect(formatStoreAddress({ prefecture: "東京都", address: "東京都千代田区デモ町1-2-3" })).toBe("東京都千代田区デモ町1-2-3");
    expect(formatStoreAddress({ prefecture: "東京都", address: "千代田区デモ町1-2-3" })).toBe("東京都 千代田区デモ町1-2-3");
  });

  it("店舗受け取り: コードを ABCD-2345 の形で大きく表示し、店舗名・住所・案内を出す。送料は ¥0 と注記", async () => {
    renderComplete(makeOrder({ ...STORE_PATCH, is_member_order: false }));
    expect(await screen.findByTestId("pickup-code")).toHaveTextContent("ABCD-2345");
    expect(screen.getByTestId("pickup-code").className).toMatch(/text-3xl/);
    expect(screen.getByTestId("pickup-code-block")).toHaveTextContent("ご来店時にこのコードと注文番号をお伝えください。マイページ（会員のとき）でも確認できます");
    expect(screen.getByTestId("store-info")).toHaveTextContent("デモ店 東京（東京都 千代田区デモ町1-2-3 デモビル1階）");
    expect(screen.getByTestId("amount-summary")).toHaveTextContent("¥0");
    expect(screen.getByTestId("store-no-shipping-note")).toHaveTextContent("店舗受け取りのため送料はかかりません");
    // 郵便番号・お届け先の住所は出さない（店舗の値で上書きされているため）
    expect(screen.queryByText(/〒/)).not.toBeInTheDocument();
  });

  it("配送: コードの枠が出ない。送料は従来の表示", async () => {
    renderComplete(makeOrder({ shipping_fee: 550, total: 5080 }));
    await screen.findByTestId("order-number");
    expect(screen.queryByTestId("pickup-code-block")).not.toBeInTheDocument();
    expect(screen.queryByTestId("store-no-shipping-note")).not.toBeInTheDocument();
    expect(screen.getByTestId("shipping-summary")).toHaveTextContent("お届け先");
  });

  it("店舗受け取りでも API がコードを返さない（null）ときは枠ごと出さない", async () => {
    renderComplete(makeOrder({ ...STORE_PATCH, pickup_code: null }));
    await screen.findByTestId("order-number");
    expect(screen.queryByTestId("pickup-code-block")).not.toBeInTheDocument();
  });

  it("is_member_order が真ならマイページの案内、偽ならゲストの案内、無い（古い保存値）なら出さない", async () => {
    const { unmount } = renderComplete(makeOrder({ is_member_order: true }));
    expect(await screen.findByTestId("member-order-note")).toHaveTextContent("ご注文はマイページの注文履歴で確認できます");
    expect(screen.queryByTestId("guest-order-note")).not.toBeInTheDocument();
    unmount();

    window.sessionStorage.clear();
    const guest = renderComplete(makeOrder({ is_member_order: false }));
    expect(await screen.findByTestId("guest-order-note")).toHaveTextContent("ゲストでのご注文です。注文番号とメールアドレスで照会できます");
    expect(screen.queryByTestId("member-order-note")).not.toBeInTheDocument();
    guest.unmount();

    window.sessionStorage.clear();
    const { is_member_order: _omit, ...legacy } = makeOrder();
    void _omit;
    renderComplete(legacy as ReturnType<typeof makeOrder>);
    await screen.findByTestId("order-number");
    expect(screen.queryByTestId("member-order-note")).not.toBeInTheDocument();
    expect(screen.queryByTestId("guest-order-note")).not.toBeInTheDocument();
  });

  it("決済失敗の注文ではコードを出さない", async () => {
    renderComplete(makeOrder({ ...STORE_PATCH, status: "payment_failed", pickup_code: "ABCD2345" }));
    await screen.findByTestId("order-number");
    expect(screen.queryByTestId("pickup-code-block")).not.toBeInTheDocument();
  });
});
