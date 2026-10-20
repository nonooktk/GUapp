import { pickBody, proxyAuthRequest } from "@/lib/server/auth-proxy";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * パスワード再設定の確定 BFF（DS-API-035 取り次ぎ。設計仕様書 4.1・DS-DEC-75、テスト IT-BFF-030b・031）。
 * 本文は token・password だけ。自動ログインはしない（`sid` を発行しない）。
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const { payload, fields } = pickBody(parsed.body, { required: ["token", "password"] });
  if (fields.length > 0) return validationError(request, fields);

  return proxyAuthRequest(request, "/auth/password-reset/confirm", { json: payload });
}
