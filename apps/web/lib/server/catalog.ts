import "server-only";

import { cookies } from "next/headers";
import { CART_TOKEN_COOKIE } from "@/lib/cookie";
import { apiFetch, type ApiResult } from "@/lib/server/api";
import { cartTokenHeaders } from "@/lib/server/cart-proxy";
import { getEnv } from "@/lib/server/env";
import type {
  Cart,
  CategoriesResponse,
  ProductDetail,
  ProductListResponse,
  PublicSettings,
} from "@/lib/types";

/**
 * Server Component から FastAPI を直接呼ぶデータ取得（設計仕様書 4.3: サーバー間通信は BFF を経由しなくてよい）。
 * 全て `cache: "no-store"`（apiFetch 内で固定）。接続不可は UpstreamUnavailableError が上がるので、
 * ページ側は `loadOrNull` で受けて「読み込めませんでした」を描く（FastAPI 停止時も build・描画を通す）。
 */

export interface ProductListQuery {
  gender?: string;
  category?: string;
  page?: number;
  per_page?: number;
}

/** `/products?gender=&category=&page=&per_page=` のクエリ文字列。空の値は付けない */
export function buildProductsQuery(q: ProductListQuery): string {
  const sp = new URLSearchParams();
  if (q.gender) sp.set("gender", q.gender);
  if (q.category) sp.set("category", q.category);
  sp.set("page", String(q.page ?? 1));
  sp.set("per_page", String(q.per_page ?? 24));
  return sp.toString();
}

export function getCategories(): Promise<ApiResult<CategoriesResponse>> {
  return apiFetch<CategoriesResponse>("/categories");
}

export function getProducts(q: ProductListQuery): Promise<ApiResult<ProductListResponse>> {
  return apiFetch<ProductListResponse>(`/products?${buildProductsQuery(q)}`);
}

export function getProduct(id: string): Promise<ApiResult<ProductDetail>> {
  return apiFetch<ProductDetail>(`/products/${encodeURIComponent(id)}`);
}

export function getPublicSettings(): Promise<ApiResult<PublicSettings>> {
  return apiFetch<PublicSettings>("/settings/public");
}

/**
 * Cookie `cart_token` があるときだけ FastAPI の GET /cart を呼ぶ。無ければ null（描画中は Cookie を発行できないため、
 * カート作成は最初の追加操作＝Route Handler に任せる）。
 */
export async function getCartFromCookie(): Promise<ApiResult<Cart> | null> {
  const store = await cookies();
  const token = store.get(CART_TOKEN_COOKIE)?.value ?? null;
  if (!token) return null;
  return apiFetch<Cart>("/cart", { headers: cartTokenHeaders(token) });
}

/** 画像 URL の base（公開 URL。クライアントへ props で渡してよい） */
export function getImageBaseUrl(): string {
  return getEnv().IMAGE_BASE_URL;
}

/**
 * 取得に失敗した（接続不可・非 2xx）ときは null を返し、例外はログだけに残す。
 * 404 など「意図した失敗」を区別したいときは apiFetch を直接使う。
 */
export async function loadOrNull<T>(promise: Promise<ApiResult<T>>, label: string): Promise<T | null> {
  try {
    const result = await promise;
    if (!result.ok) {
      console.error(`[page] ${label} failed`, { status: result.status, code: result.error.code });
      return null;
    }
    return result.data;
  } catch (err) {
    console.error(`[page] ${label} unavailable`, err instanceof Error ? err.message : err);
    return null;
  }
}
