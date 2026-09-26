import "server-only";

import { CART_TOKEN_COOKIE, readCookie } from "@/lib/cookie";
import { resolveClientIp } from "@/lib/client-ip";
import { apiFetch, UpstreamUnavailableError } from "@/lib/server/api";
import { cartTokenHeaders } from "@/lib/server/cart-proxy";
import { getEnv } from "@/lib/server/env";

/**
 * 注文系 BFF の共通取り次ぎ（DS-API-021〜023・設計仕様書 4.3・7.2、テスト IT-BFF-01/02）。
 * - Cookie `cart_token` を `X-Cart-Token` に載せる（カートの特定。lookup では不要だが付いても害はない）
 * - `X-Internal-Token` は apiFetch が付ける
 * - `X-Forwarded-For` に利用者の送信元 IP を載せる（lookup のレート制限 100 回/時/IP が使う）。
 *   **利用者が送ってきた `X-Forwarded-For` は転送しない**（偽装でレート制限を回避／他人を 429 にできるため。ST 実施記録 2026-09-24 🟡）。
 *   `X-Client-IP`（App Service）→ `TRUSTED_PROXY_HOPS` で右から切った XFF → 接続元（`127.0.0.1`）の順。判定は lib/client-ip.ts の resolveClientIp
 * - 応答本文は成功ならそのまま、エラーは sanitizeErrorBody 済みの `{code, ...}`。`Retry-After` は 429 のために転送する
 * - **配送先・メールなど個人情報をログに書かない**（本文を出力しない。接続不可時も path だけ）
 * - CSRF 検証は各 Route Handler が先頭で行う（verifyCsrf）。ここには置かない
 */

export const FORWARDED_FOR_HEADER = "X-Forwarded-For";

/** FastAPI へ渡す利用者 IP。信頼できる送信元だけを使い、無ければ空にせず 127.0.0.1 */
export function clientIp(request: Request): string {
  return resolveClientIp(request.headers, { trustedProxyHops: getEnv().TRUSTED_PROXY_HOPS });
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
