# apps/web — GU EC サイト フロントエンド（Next.js・BFF）

設計仕様書 `docs/03_設計仕様書/GU_ECsite_設計仕様書_P1_draft-v3.md` の 4.1（BFF）・6.2（共通レイアウト）・7.2（秘密情報）・7.3（Cookie）に対応する Next.js アプリ。

## 版（Wave 0 時点・`pnpm-lock.yaml` で固定）

| 項目 | 版 |
| --- | --- |
| Node.js | 24.14 |
| pnpm | 12.4 |
| Next.js | 16.3.5（App Router・Turbopack・`output: "standalone"`） |
| React | 19.2.8 |
| TypeScript | 5.9 |
| Tailwind CSS | 4.3 |
| Vitest / Testing Library | 5.0 / react 16.3・jest-dom 7.0 |

## 起動手順

1. 依存の導入: `pnpm install`
2. `apps/web/.env.local` を作成する（gitignore 済み・コミット禁止）。置くキーは次の 5 つ。値はこの README に書かない（ルートの `.env.example` 参照）。

   | キー | 必須 | 用途 |
   | --- | --- | --- |
   | `API_BASE_URL` | 必須 | FastAPI の URL（サーバー側のみ。`NEXT_PUBLIC_` を付けない） |
   | `INTERNAL_TOKEN` | 必須 | BFF → FastAPI の内部認証（api と同じ値） |
   | `IMAGE_BASE_URL` | 必須 | 商品画像の配信ベース URL |
   | `SESSION_COOKIE_DOMAIN` | 任意 | Cookie の Domain 属性。ローカルは空 |
   | `APP_ENV` | 任意 | `development`（既定）/ `test` / `production`。`production` のときだけ Cookie に `Secure` が付く |

   必須が欠けている、または `NEXT_PUBLIC_` 付きで名前に `TOKEN`・`SECRET`・`PASSWORD`・`DATABASE_URL`・`API_KEY` を含む変数があると、環境変数ローダーが例外を投げて起動を拒否する（UT-WEB-05）。

3. 開発サーバー: `pnpm dev` → http://localhost:3000
4. 本番ビルド: `pnpm build` → `.next/standalone/` に `server.js` が出力される（App Service では `node server.js`）

## テスト

```
pnpm lint        # ESLint（eslint-config-next）
pnpm typecheck   # tsc --noEmit
pnpm test        # Vitest（jsdom）。tests/**/*.test.{ts,tsx}
```

テストファイル名にはテスト設計書の ID を含める（例: `tests/ut-web-05.env-validation.test.ts`）。

## ディレクトリ

```
app/
  layout.tsx            共通レイアウト（lang="ja"・ヘッダー・フッター）
  page.tsx              ホーム DS-SCR-001（Wave 0 は仮置き）
  api/health/route.ts   BFF 疎通確認。FastAPI 未起動なら 503 {code:"upstream_unavailable"}
  api/cart/route.ts     匿名カート Cookie `cart_token` の発行（Wave 0 は Cookie 方式の確認のみ）
components/
  Header.tsx            ≡ メニュー／GU ロゴ／検索・お気に入り・カート（点数バッジ）・会員
  Footer.tsx            企業情報・利用規約・プライバシー・特商法・FAQ
lib/
  env-validation.ts     validateEnv（純粋関数。UT-WEB-05）
  cookie.ts             Set-Cookie 文字列の組み立て（純粋関数。ST-SEC-07 の土台）
  server/env.ts         `import "server-only"`。process.env を validateEnv に渡すローダー
  server/api.ts         `import "server-only"`。FastAPI 呼び出し（X-Internal-Token 付与・エラー本文の整形）
  server/cart-token.ts  `import "server-only"`。暗号学的乱数 32 バイトの base64url トークン
tests/                  Vitest（setup.ts・stubs/server-only.ts）
```

## 秘密情報の取り扱い（設計 7.2）

- 秘密を触るモジュールは `lib/server/` に置き、先頭で `import "server-only"` する。クライアントコンポーネント（`"use client"`）から import すると `pnpm build` が失敗する（Wave 0 で実証済み）。
- `lib/server/api.ts` は FastAPI の応答本文をそのまま返さず、エラーは `{code, ...許可した詳細キー}` だけ通す。接続不可・タイムアウトは `UpstreamUnavailableError`。

## BFF の手動確認（curl）

```
curl -i http://localhost:3000/api/cart     # Set-Cookie: cart_token=...; Path=/; Max-Age=7776000; HttpOnly; SameSite=Lax
curl -i http://localhost:3000/api/health   # FastAPI 未起動: 503 {"code":"upstream_unavailable"}
```
