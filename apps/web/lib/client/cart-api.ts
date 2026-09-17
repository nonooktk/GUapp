import { CSRF_HEADER, CSRF_TOKEN_COOKIE, isCsrfTokenShape } from "@/lib/csrf-validation";
import type { ApiErrorBody, Cart, ProductListResponse } from "@/lib/types";

/**
 * ブラウザから BFF（/api/cart*）を呼ぶ薄いクライアント。
 * - 状態変更は `X-CSRF-Token` に Cookie `csrf_token` の値を載せる（Double Submit Cookie。設計仕様書 7.3）
 * - `csrf_token` が未発行なら先に `GET /api/cart` を呼んで発行させる（ここで FastAPI 側にカートが作られる）
 * - 失敗は CartApiError（status と `{code,...}` 本文）で投げる。文言化は lib/cart-messages.ts
 */

export class CartApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: ApiErrorBody | null,
  ) {
    super(`cart api ${status} ${body?.code ?? ""}`);
    this.name = "CartApiError";
  }
}

/** `document.cookie` から csrf_token を読む（純粋に文字列処理。テストしやすいよう引数で受ける） */
export function readCsrfCookie(cookieString: string): string | null {
  for (const part of cookieString.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === CSRF_TOKEN_COOKIE) {
      const v = rest.join("=");
      return isCsrfTokenShape(v) ? v : null;
    }
  }
  return null;
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

async function requestJson<T>(input: string, init: RequestInit): Promise<T> {
  const res = await fetch(input, { ...init, credentials: "same-origin", cache: "no-store" });
  if (!res.ok) {
    throw new CartApiError(res.status, await parseJson<ApiErrorBody>(res));
  }
  const data = await parseJson<T>(res);
  if (data === null) throw new CartApiError(res.status, { code: "bad_response" });
  return data;
}

/** GET /api/cart。Cookie 発行（cart_token・csrf_token）の副作用を持つ */
export function fetchCart(): Promise<Cart> {
  return requestJson<Cart>("/api/cart", { method: "GET" });
}

/** CSRF トークンを返す。未発行なら GET /api/cart で発行させてから読む */
export async function ensureCsrfToken(): Promise<string> {
  let token = readCsrfCookie(document.cookie);
  if (token) return token;
  await fetchCart();
  token = readCsrfCookie(document.cookie);
  if (!token) throw new CartApiError(403, { code: "forbidden" });
  return token;
}

async function mutate<T>(input: string, method: "POST" | "PATCH" | "DELETE", json?: unknown): Promise<T> {
  const csrf = await ensureCsrfToken();
  const headers: Record<string, string> = { [CSRF_HEADER]: csrf, Accept: "application/json" };
  if (json !== undefined) headers["Content-Type"] = "application/json";
  return requestJson<T>(input, { method, headers, body: json !== undefined ? JSON.stringify(json) : undefined });
}

export function addCartItem(variantId: number, quantity: number): Promise<Cart> {
  return mutate<Cart>("/api/cart/items", "POST", { variant_id: variantId, quantity });
}

export function updateCartItem(itemId: number, quantity: number): Promise<Cart> {
  return mutate<Cart>(`/api/cart/items/${itemId}`, "PATCH", { quantity });
}

export function deleteCartItem(itemId: number): Promise<Cart> {
  return mutate<Cart>(`/api/cart/items/${itemId}`, "DELETE");
}

/** 一覧の「もっと見る」。`query` は `gender=women&category=tops` の形（page は上書きする） */
export function fetchProductsPage(query: string, page: number): Promise<ProductListResponse> {
  const sp = new URLSearchParams(query);
  sp.set("page", String(page));
  sp.set("per_page", "24");
  return requestJson<ProductListResponse>(`/api/products?${sp.toString()}`, { method: "GET" });
}
