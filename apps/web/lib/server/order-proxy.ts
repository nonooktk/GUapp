import "server-only";

import { CART_TOKEN_COOKIE, readCookie } from "@/lib/cookie";
import { apiFetch, UpstreamUnavailableError } from "@/lib/server/api";
import { cartTokenHeaders } from "@/lib/server/cart-proxy";

/**
 * 注文系 BFF の共通取り次ぎ（DS-API-021〜023・設計仕様書 4.3・7.2、テスト IT-BFF-01/02）。
 * - Cookie `cart_token` を `X-Cart-Token` に載せる（カートの特定。lookup では不要だが付いても害はない）
 * - `X-Internal-Token` は apiFetch が付ける
 * - `X-Forwarded-For` に接続元 IP を載せる（lookup のレート制限 100 回/時/IP が使う）。`x-forwarded-for` の先頭、無ければ `127.0.0.1`
 * - 応答本文は成功ならそのまま、エラーは sanitizeErrorBody 済みの `{code, ...}`。`Retry-After` は 429 のために転送する
 * - **配送先・メールなど個人情報をログに書かない**（本文を出力しない。接続不可時も path だけ）
 * - CSRF 検証は各 Route Handler が先頭で行う（verifyCsrf）。ここには置かない
 */

export const FORWARDED_FOR_HEADER = "X-Forwarded-For";
const FALLBACK_CLIENT_IP = "127.0.0.1";

/** IP らしい文字列だけ通す（ヘッダ注入や巨大値の転送を避ける） */
const IP_LIKE = /^[0-9a-fA-F.:]{3,45}$/;

/** `x-forwarded-for` の先頭を接続元 IP として使う。無ければ空にせず 127.0.0.1 */
export function clientIp(request: Request): string {
  const xff = request.headers.get("x-forwarded-for");
  if (xff) {
    const first = xff.split(",")[0]?.trim() ?? "";
    if (IP_LIKE.test(first)) return first;
  }
  return FALLBACK_CLIENT_IP;
}

export interface OrderProxyInit {
  json?: unknown;
}

export async function proxyOrderRequest(request: Request, path: string, init: OrderProxyInit = {}): Promise<Response> {
  const cartToken = readCookie(request.headers.get("cookie"), CART_TOKEN_COOKIE);
  const headers = new Headers({ "Cache-Control": "no-store" });

  let result;
  try {
    result = await apiFetch<unknown>(path, {
      method: "POST",
      json: init.json ?? {},
      headers: { ...cartTokenHeaders(cartToken), [FORWARDED_FOR_HEADER]: clientIp(request) },
      // 注文確定は在庫引当・決済スタブを含むため、カート系より少し長めに待つ
      timeoutMs: 15000,
    });
  } catch (err) {
    if (err instanceof UpstreamUnavailableError) {
      return Response.json({ code: "upstream_unavailable" }, { status: 503, headers });
    }
    // 本文（個人情報）は出さない。メッセージだけ
    console.error("[api/orders] unexpected error", { path, reason: err instanceof Error ? err.message : String(err) });
    return Response.json({ code: "internal_error", message: "処理中にエラーが発生しました" }, { status: 500, headers });
  }

  if (!result.ok) {
    // 429 rate_limited の Retry-After は利用者への案内に使うので透過する（数字か HTTP 日付のみ）
    if (result.status === 429 && result.retryAfter && /^[0-9A-Za-z ,:-]{1,40}$/.test(result.retryAfter)) {
      headers.set("Retry-After", result.retryAfter);
    }
    return Response.json(result.error, { status: result.status, headers });
  }
  return Response.json(result.data, { status: result.status, headers });
}
