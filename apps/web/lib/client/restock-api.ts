import { post } from "@/lib/client/order-api";

/**
 * 再入荷のお知らせ申込（`POST /api/restock-notifications`。設計仕様書 4.5・DS-API-007）。
 * 200 `{status:"registered"}`。失敗は OrderApiError（status と `{code,...}` 本文）。文言化は lib/restock-messages.ts
 */
export async function registerRestock(variantId: number, email: string): Promise<void> {
  await post<{ status: string }>("/api/restock-notifications", { variant_id: variantId, email });
}
