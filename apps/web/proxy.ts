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
 * - 静的アセット（`_next/static`・`_next/image`・favicon 等）は対象外にする。理由は
 *   公開追補 設計仕様書 7 章参照（ハッシュ付きファイル名で認証済み HTML 経由でしか
 *   URL を知り得ず、内容もビルド成果物であって個人情報・非公開の業務データを含まないため）
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { parseBasicAuthConfig, verifyBasicAuthHeader } from "@/lib/basic-auth";

// モジュール読み込み時に一度だけ評価する。片方だけ設定されている設定ミスは、
// ここで例外を投げてプロセスの起動（または最初のリクエスト）で気づけるようにする。
const basicAuthConfig = parseBasicAuthConfig(process.env);

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)"],
};

const WWW_AUTHENTICATE = 'Basic realm="GUapp demo", charset="UTF-8"';

export function proxy(request: NextRequest): Response {
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
