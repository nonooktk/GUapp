import { pickBody, proxyAuthRequest } from "@/lib/server/auth-proxy";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * ログイン BFF（DS-API-032 取り次ぎ。設計仕様書 3.1・4.1・7.3・DS-DEC-72・85、テスト IT-BFF-030a〜f）。
 * - CSRF 検証に失敗したら 403 で FastAPI へ到達させない。本文は 8KB まで（413）
 * - 本文は email・password だけを拾って転送する（`role`・`is_admin`・`session_token` などは落とす）
 * - 成功したら応答の `session_token` を Cookie `sid`（HttpOnly・SameSite=Lax・Path=/・Max-Age=86400。production は Secure）にし、
 *   本文から除く。`csrf_token` を発行し直す（ログイン CSRF・セッション固定への備え）
 * - 失敗（401／403／429／503）は `{code}` をそのまま返し、`Set-Cookie` を出さない。成功・失敗とも `Cache-Control: no-store`
 * - Cookie `sid` が残っていれば `X-Session-Token` で渡し、FastAPI が古いセッション行を削除する（再発行）
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const { payload, fields } = pickBody(parsed.body, { required: ["email", "password"] });
  if (fields.length > 0) return validationError(request, fields);

  return proxyAuthRequest(request, "/auth/login", { json: payload, mode: "login" });
}
