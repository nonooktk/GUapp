import { issueCsrfCookieIfMissing } from "@/lib/server/csrf";

/**
 * CSRF トークンの発行（設計仕様書 P2 追補c 4.5・DS-DEC-121、テスト IT-BFF-056・ST-SEC-95）。
 * `csrf_token` Cookie が未発行（または形が不正）なら発行する。204。FastAPI は呼ばない。
 * ログイン画面が最初の POST の前に呼ぶ（顧客向けの `GET /api/cart` は FastAPI にカートを作るため、管理画面では使わない）。
 * `/admin/api/*` は proxy.ts の回数制限で `/api/*` と同じ「API」の枠（120 回/分）に数える（DS-DEC-126）。
 */

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const headers = new Headers({ "Cache-Control": "no-store" });
  const cookie = issueCsrfCookieIfMissing(request);
  if (cookie) headers.append("Set-Cookie", cookie);
  return new Response(null, { status: 204, headers });
}
