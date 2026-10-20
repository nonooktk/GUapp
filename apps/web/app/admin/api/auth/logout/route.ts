import { proxyAdminRequest } from "@/lib/server/admin-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 管理ログアウト BFF（DS-API-050a 取り次ぎ。設計仕様書 P2 追補c 4.1・4.5、テスト IT-BFF-052）。
 * - POST のみ（GET の窓口は無い＝405）。本文なし。CSRF 検証に失敗したら 403 で FastAPI へ到達させない
 * - `asid` を `X-Admin-Session-Token` に載せて FastAPI を呼ぶ。成功（204）・失敗・接続不可のどれでも、ブラウザへ `asid` の削除 Cookie
 *   （Max-Age=0・Path=/admin）と新しい `csrf_token` を返す
 */

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;
  return proxyAdminRequest(request, "/admin/auth/logout", { mode: "logout", method: "POST" });
}
