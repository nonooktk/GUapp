/**
 * サイト全体・BFF `/api/*` を保護する HTTP Basic 認証（公開追補 設計仕様書 7 章・DS-DEC-49）。
 *
 * Next.js 16 で `middleware.ts` は非推奨になり `proxy.ts` に改称された
 * （`node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md`。
 * `apps/web/AGENTS.md` の指示どおり、コードを書く前に同梱ドキュメントを確認済み）。
 * 既定ランタイムは Node.js（v16 での変更点）で、`node:crypto` を使う `lib/basic-auth.ts` を
 * そのまま呼べる。
 *
 * 設定方針:
 * - `BASIC_AUTH_USER`・`BASIC_AUTH_PASSWORD` が両方未設定なら認証なし（ローカル開発を妨げない）
 * - 片方だけ設定はモジュール読み込み時（起動時相当）に例外で失敗させる。設定漏れのまま
 *   無防備に公開してしまう事故を防ぐ
 * - 回数制限（セキュリティ強化 S1）: IP ごと・60 秒で `/api/*` は 120 回、ページ・RSC・prefetch は 600 回
 *   （`RATE_LIMIT_API_PER_MIN`・`RATE_LIMIT_PAGE_PER_MIN` で上書き）。超えたら 429 `{"code":"rate_limited"}` と
 *   `Retry-After`。Basic 認証より前に判定し、総当たりも数える。429 のとき FastAPI は呼ばない。
 *   カウンタはこのプロセスのメモリ内（lib/server/rate-limit.ts。複数インスタンスでは共有されない）
 * - 静的アセット（`_next/static`・`_next/image`・favicon 等）は対象外にする。理由は
 *   公開追補 設計仕様書 7 章参照（ハッシュ付きファイル名で認証済み HTML 経由でしか
 *   URL を知り得ず、内容もビルド成果物であって個人情報・非公開の業務データを含まないため）
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { parseBasicAuthConfig, verifyBasicAuthHeader } from "@/lib/basic-auth";
import { resolveClientIp } from "@/lib/client-ip";
import { parseRateLimitEnv, parseTrustedProxyHops } from "@/lib/env-validation";
import { maskIp, writeRejectionLog } from "@/lib/security-log";
import { createRateLimiter, rateLimitedResponse } from "@/lib/server/rate-limit";

// モジュール読み込み時に一度だけ評価する。片方だけ設定されている設定ミスは、
// ここで例外を投げてプロセスの起動（または最初のリクエスト）で気づけるようにする。
const basicAuthConfig = parseBasicAuthConfig(process.env);

// 回数制限の上限と信頼ホップ数。不正な値はここで例外にして、起動（または最初のリクエスト）で気づけるようにする。
// proxy は必須の環境変数（API_BASE_URL など）を要求しないため、getEnv ではなく純粋関数で process.env を読む。
const rateLimiter = createRateLimiter(parseRateLimitEnv(process.env));
const trustedProxyHops = parseTrustedProxyHops(process.env);

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)"],
};

const WWW_AUTHENTICATE = 'Basic realm="GUapp demo", charset="UTF-8"';

export function proxy(request: NextRequest): Response {
  const { pathname } = request.nextUrl;
  const ip = resolveClientIp(request.headers, { trustedProxyHops });
  const limited = rateLimiter.check(pathname, ip);
  if (limited && !limited.allowed) {
    writeRejectionLog({
      event: "rate_limited",
      path: pathname,
      method: request.method,
      status: 429,
      code: "rate_limited",
      ip: maskIp(ip),
    });
    return rateLimitedResponse(limited.retryAfterSec);
  }

  if (basicAuthConfig === null) {
    return NextResponse.next();
  }

  const header = request.headers.get("authorization");
  if (verifyBasicAuthHeader(header, basicAuthConfig.user, basicAuthConfig.password)) {
    return NextResponse.next();
  }

  return new Response(null, {
    status: 401,
    headers: { "WWW-Authenticate": WWW_AUTHENTICATE },
  });
}

export default proxy;
