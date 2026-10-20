import { chatResetResponse } from "@/lib/server/chat-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 「新しい相談を始める」BFF（設計仕様書 P2 追補d 4.4、テスト IT-BFF-AI-11）。
 * CSRF を検証したうえで Cookie `chat_token` を消すだけ（FastAPI は呼ばない）。次の質問で新しいセッションが作られ、往復数は 0 に戻る。
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;
  return chatResetResponse();
}
