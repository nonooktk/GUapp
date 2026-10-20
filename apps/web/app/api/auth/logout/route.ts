import { proxyAuthRequest } from "@/lib/server/auth-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * ログアウト BFF（DS-API-033 取り次ぎ。設計仕様書 4.1・DS-DEC-72・85、テスト IT-BFF-030b・030c）。
 * - POST のみ（GET の窓口は無い＝405）。本文なし。CSRF 検証に失敗したら 403 で FastAPI へ到達させない
 * - `sid` を `X-Session-Token` に載せて FastAPI を呼ぶ。成功（204）・失敗・接続不可のどれでも、ブラウザへ `sid` の削除 Cookie（Max-Age=0）と
 *   新しい `csrf_token` を返す
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;
  return proxyAuthRequest(request, "/auth/logout", { mode: "logout" });
}
