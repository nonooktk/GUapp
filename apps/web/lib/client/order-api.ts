import { CSRF_HEADER } from "@/lib/csrf-validation";
import { CartApiError, ensureCsrfToken } from "@/lib/client/cart-api";
import type { ApiErrorBody, OrderCreateBody, OrderResponse, PrepareResponse } from "@/lib/types";

/**
 * ブラウザから注文系 BFF（`/api/checkout/prepare`・`/api/orders`・`/api/orders/[n]/lookup`）を呼ぶ薄いクライアント。
 * - すべて POST なので `X-CSRF-Token` を載せる（未発行なら cart-api の ensureCsrfToken が GET /api/cart で発行させる）
 * - 失敗は CartApiError（status と `{code,...}` 本文）で投げる。戻し先の判定は lib/order-errors.ts
 * - `retryAfterSec` は 429 のときだけ（lookup の案内文に使う）
 */

export class OrderApiError extends CartApiError {
  constructor(
    status: number,
    body: ApiErrorBody | null,
    readonly retryAfterSec: number | null = null,
  ) {
    super(status, body);
    this.name = "OrderApiError";
  }
}

async function parseJson<T>(res: Response): Promise<T | null> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

async function post<T>(input: string, json?: unknown): Promise<{ status: number; data: T }> {
  const csrf = await ensureCsrfToken();
  const headers: Record<string, string> = { [CSRF_HEADER]: csrf, Accept: "application/json" };
  if (json !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(input, {
    method: "POST",
    headers,
    body: json !== undefined ? JSON.stringify(json) : undefined,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!res.ok) {
    const ra = res.headers.get("Retry-After");
    const sec = ra && /^\d+$/.test(ra) ? Number(ra) : null;
    throw new OrderApiError(res.status, await parseJson<ApiErrorBody>(res), sec);
  }
  const data = await parseJson<T>(res);
  if (data === null) throw new OrderApiError(res.status, { code: "bad_response" });
  return { status: res.status, data };
}

/** POST /api/checkout/prepare → 冪等キー・明細・金額（DS-API-021） */
export async function prepareCheckout(): Promise<PrepareResponse> {
  return (await post<PrepareResponse>("/api/checkout/prepare")).data;
}

/** POST /api/orders → 201（新規）／200（同じキーの再送）。どちらも注文応答（DS-API-022） */
export function createOrder(body: OrderCreateBody): Promise<{ status: number; data: OrderResponse }> {
  return post<OrderResponse>("/api/orders", body);
}

/** POST /api/orders/[n]/lookup → 注文応答（DS-API-023）。404 は番号・メールを区別しない */
export async function lookupOrder(orderNumber: string, guestEmail: string): Promise<OrderResponse> {
  return (await post<OrderResponse>(`/api/orders/${encodeURIComponent(orderNumber)}/lookup`, { guest_email: guestEmail })).data;
}
