import type { OrderResponse } from "@/lib/types";

/** 注文応答（P2-b の項目つき）の組み立て。配送の既定に、店舗受け取りなどの差分を重ねる */
export function makeOrder(patch: Partial<OrderResponse> = {}): OrderResponse {
  return {
    order_number: "GU-261024-ABCDEFGH",
    status: "accepted",
    items: [
      { product_name: "スムースコットンT", color: "黒", size: "M", unit_price: 1990, quantity: 2, line_total: 3980 },
      { product_name: "リブレギンス", color: "グレー", size: "L", unit_price: 550, quantity: 1, line_total: 550 },
    ],
    subtotal: 4530,
    shipping_fee: 0,
    total: 4530,
    tax_included: 411,
    tax_rate: "0.10",
    ship_name: "デモ 一郎",
    ship_postal_code: "0000001",
    ship_address: "東京都　千代田区　デモ町1-2-3",
    ship_phone: "09000000000",
    guest_email: "demo-member1@example.com",
    receive_method: "delivery",
    payment_method: "card",
    ordered_at: "2026-10-24T01:15:00Z",
    store: null,
    pickup_code: null,
    tracking_number: null,
    status_label: "受付済",
    is_member_order: true,
    ...patch,
  };
}

export const STORE_PATCH: Partial<OrderResponse> = {
  receive_method: "store",
  shipping_fee: 0,
  store: { name: "デモ店 東京", prefecture: "東京都", address: "千代田区デモ町1-2-3 デモビル1階" },
  pickup_code: "ABCD2345",
};
