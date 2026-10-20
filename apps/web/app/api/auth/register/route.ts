import { pickBody, proxyAuthRequest } from "@/lib/server/auth-proxy";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 会員登録 BFF（DS-API-030 取り次ぎ。設計仕様書 4.1・4.7・DS-DEC-71・76、テスト IT-BFF-030b・031）。
 * - CSRF 検証（Origin → Double Submit Cookie）に失敗したら 403 で FastAPI へ到達させない。本文は 8KB まで（413）
 * - 本文は email・password・name・birth_date・gender・personalize_opt_in だけを拾って転送する（`role` などは落とす）。形・長さ・弱いパスワードの判定は FastAPI
 * - 202 `{status:"accepted"}` は新規・既登録で同じ。セッションは発行しない
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const { payload, fields } = pickBody(parsed.body, {
    required: ["email", "password", "name"],
    optionalStrings: ["birth_date", "gender"],
    optionalBooleans: ["personalize_opt_in"],
  });
  if (fields.length > 0) return validationError(request, fields);

  return proxyAuthRequest(request, "/auth/register", { json: payload });
}
