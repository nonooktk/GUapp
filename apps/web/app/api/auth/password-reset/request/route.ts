import { pickBody, proxyAuthRequest } from "@/lib/server/auth-proxy";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * パスワード再設定の要求 BFF（DS-API-034 取り次ぎ。設計仕様書 4.1・DS-DEC-71・75、テスト IT-BFF-030b・031）。
 * 本文は email だけ。会員の有無にかかわらず FastAPI は 200 `{status:"accepted"}` を返す。
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const { payload, fields } = pickBody(parsed.body, { required: ["email"] });
  if (fields.length > 0) return validationError(request, fields);

  return proxyAuthRequest(request, "/auth/password-reset/request", { json: payload });
}
