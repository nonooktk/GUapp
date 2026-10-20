import { validateChatRequestBody } from "@/lib/chat-validation";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { proxyChatMessage } from "@/lib/server/chat-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 質問の送信 BFF（DS-API-041 取り次ぎ。設計仕様書 P2 追補d 4.4、テスト IT-BFF-AI-01〜09・12）。
 * 順序: ① CSRF（Origin → トークン）→ ② 本文 8192 バイトまで → ③ 形の検査（400 validation_error。FastAPI は呼ばない）→ ④ 取り次ぎ。
 * 本文は `message`・`product_id` だけを拾って転送する（他のキーは落とす）。
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const checked = validateChatRequestBody(parsed.body);
  if (!checked.ok) return validationError(request, checked.fields);

  return proxyChatMessage(request, checked.payload);
}
