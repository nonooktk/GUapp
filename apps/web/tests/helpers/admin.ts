import type { AdminOrderDetail, AdminOrderListItem, AdminProductDetail, AdminSettingItem } from "@/lib/admin-types";

/**
 * P2-c 管理画面のテスト共通部品（テスト設計書 UT-WEB-40〜54・IT-BFF-050〜056）。
 * BFF のテストは helpers/bff.ts を先頭で import して環境変数を用意してから使う。
 */

/** 管理用セッション Cookie `asid` のダミー値（43 文字の base64url） */
export const ASID_OLD = "oldAsidAAAA_-0123456789abcdefghijklmnopqrst"; // gitleaks:allow // pragma: allowlist secret（43 文字）
export const ASID_NEW = "newAsidBBBB_-0123456789abcdefghijklmnopqrst"; // gitleaks:allow // pragma: allowlist secret（43 文字）
export const ASID_ATTACKER = "attackerChosen_-0123456789abcdefghijklmnopq"; // gitleaks:allow // pragma: allowlist secret（43 文字）

export function makeAdminProduct(patch: Partial<AdminProductDetail> = {}): AdminProductDetail {
  return {
    product_id: 12,
    name: "スムースコットンT（レディース）",
    price_incl_tax: 1990,
    published: true,
    updated_at: "2026-10-20T00:00:00Z",
    variants: [
      { variant_id: 7, sku: "GU-012-BK-M", color: "ブラック", size: "M", stock: 0, restock_waiting: 2 },
      { variant_id: 8, sku: "GU-012-BK-L", color: "ブラック", size: "L", stock: 4, restock_waiting: 0 },
    ],
    ...patch,
  };
}

export function makeAdminOrder(patch: Partial<AdminOrderDetail> = {}): AdminOrderDetail {
  return {
    order_number: "GU-261024-ABCDEFGH",
    ordered_at: "2026-10-24T01:15:00Z",
    status: "accepted",
    status_label: "受付済",
    receive_method: "delivery",
    store: null,
    items: [
      { product_name: "スムースコットンT", color: "黒", size: "M", unit_price: 1990, quantity: 2 },
      { product_name: "リブレギンス", color: "グレー", size: "L", unit_price: 550, quantity: 1 },
    ],
    subtotal: 4530,
    shipping_fee: 0,
    discount: 0,
    total: 4530,
    tax_included: 411,
    tax_rate: "0.10",
    payment: { provider: "stub", result: "succeeded" },
    customer: {
      type: "guest",
      name: "デモ 一郎",
      email_masked: "d***@example.com",
      phone_masked: "*******5678",
      postal_code: "0000001",
      address: "東京都千代田区デモ町1-2-3",
    },
    tracking_number: null,
    available_transitions: [{ status: "preparing", label: "出荷準備中", accepts_tracking_number: false }],
    ...patch,
  };
}

export function makeAdminOrderListItem(patch: Partial<AdminOrderListItem> = {}): AdminOrderListItem {
  return {
    order_number: "GU-261024-ABCDEFGH",
    ordered_at: "2026-10-24T01:15:00Z",
    status: "accepted",
    status_label: "受付済",
    receive_method: "delivery",
    total: 3980,
    item_count: 2,
    customer_type: "guest",
    email_masked: "t***@example.com",
    ...patch,
  };
}

export const ADMIN_SETTING_ITEMS: AdminSettingItem[] = [
  { key: "tax_rate", label: "消費税率", value: "0.10", editable: true, unit: null, min: "0.00", max: "0.30" },
  { key: "shipping_fee", label: "送料", value: 550, editable: true, unit: "円", min: 0, max: 5000 },
  { key: "free_shipping_threshold", label: "送料無料の下限", value: 4990, editable: true, unit: "円", min: 0, max: 100000 },
  { key: "payment_timeout_minutes", label: "決済待ちの期限", value: 30, editable: false, unit: "分", min: null, max: null },
];
