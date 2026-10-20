import { pickBody } from "@/lib/server/auth-proxy";
import { proxyAdminRequest } from "@/lib/server/admin-proxy";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 管理ログイン BFF（DS-API-050 取り次ぎ。設計仕様書 P2 追補c 3.1・4.1・4.5・DS-DEC-108・121、テスト IT-BFF-050・051）。
 * - CSRF 検証に失敗したら 403 で FastAPI へ到達させない。本文は 8KB まで（413）
 * - 本文は login_id・password だけを拾って転送する（`role`・`session_token` などは落とす）
 * - 成功したら応答の `session_token` を Cookie `asid`（HttpOnly・SameSite=Strict・Path=/admin・Max-Age=28800。production は Secure）にし、
 *   本文から除く。`csrf_token` を発行し直す（ログイン CSRF・セッション固定への備え）
 * - 失敗（401／403／429／503）は `{code}` をそのまま返し、`Set-Cookie` を出さない。成功・失敗とも `Cache-Control: no-store`
 * - 遷移先（`next`）は受けない（オープンリダイレクトの面を作らない）。ログイン後は画面側が常に `/admin/products` へ移す
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const { payload, fields } = pickBody(parsed.body, { required: ["login_id", "password"] });
  if (fields.length > 0) return validationError(request, fields);

  return proxyAdminRequest(request, "/admin/auth/login", { json: payload, mode: "login", method: "POST" });
}
