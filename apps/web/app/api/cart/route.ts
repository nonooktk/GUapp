import { proxyCartRequest } from "@/lib/server/cart-proxy";

/**
 * カート取得 BFF（DS-API-010 取り次ぎ。設計仕様書 4.3・7.3）。
 * Cookie `cart_token` を `X-Cart-Token` に載せて FastAPI `GET /cart` を呼ぶ。トークン無し・未知なら FastAPI が
 * 新規発行して返すので、応答の `cart_token` が Cookie と違えば `Set-Cookie` で更新する。
 * CSRF トークン Cookie `csrf_token` も未発行ならここで発行する（クライアントは追加操作の前にこの API を叩く）。
 */

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return proxyCartRequest(request, "/cart", { method: "GET" });
}
