import { proxyChatStatus } from "@/lib/server/chat-proxy";

/**
 * AI アシスタントの利用可否 BFF（DS-API-040 取り次ぎ。設計仕様書 P2 追補d 4.1・4.2、テスト IT-BFF-AI-10）。
 * 読み取り専用のため CSRF 検証なし。FastAPI の status のキーだけを返す。
 */

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return proxyChatStatus(request);
}
