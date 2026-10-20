import { pickBody, proxyAuthRequest } from "@/lib/server/auth-proxy";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * メール確認 BFF（DS-API-031 取り次ぎ。設計仕様書 4.1・DS-DEC-74、テスト IT-BFF-030b・031）。
 * リンクを開いただけでは確認しない（画面のボタンで POST する）。token の形の検査は FastAPI（400／404）。
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const { payload, fields } = pickBody(parsed.body, { required: ["token"] });
  if (fields.length > 0) return validationError(request, fields);

  return proxyAuthRequest(request, "/auth/verify-email", { json: payload });
}
