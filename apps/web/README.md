# apps/web — GU EC サイト フロントエンド（Next.js・BFF）

設計仕様書 `docs/03_設計仕様書/GU_ECsite_設計仕様書_P1_draft-v3.md` の 4.1・4.3（BFF）・6.2〜6.6（画面）・7.2（秘密情報）・7.3（Cookie・CSRF）に対応する Next.js アプリ。Wave 1 で SCR-001〜004 の 4 画面・カート BFF・CSRF・ヘッダーバッジを実装した。

## 版（`pnpm-lock.yaml` で固定）

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
   | `IMAGE_BASE_URL` | 必須 | 商品画像の配信ベース URL。FastAPI の `image_path`（`products/001/1.jpg`）を後ろに付けて表示 URL にする。ローカルは `public/` の配信元＝自サイトのオリジン（例: `http://localhost:3000`） |
   | `SESSION_COOKIE_DOMAIN` | 任意 | Cookie の Domain 属性。ローカルは空 |
   | `APP_ENV` | 任意 | `development`（既定）/ `test` / `production`。`production` のときだけ Cookie に `Secure` が付く |

   必須が欠けている、または `NEXT_PUBLIC_` 付きで名前に `TOKEN`・`SECRET`・`PASSWORD`・`DATABASE_URL`・`API_KEY` を含む変数があると、環境変数ローダーが例外を投げて起動を拒否する（UT-WEB-05）。

3. 商品画像のプレースホルダー生成（初回のみ）: `node scripts/gen-placeholders.mjs` → `public/products/001〜030/1.jpg`（中身は単色 PNG。依存追加なし）
4. 開発サーバー: `pnpm dev` → http://localhost:3000 （FastAPI は `API_BASE_URL` で起動しておく。止まっていても各ページは「読み込めませんでした」を表示して描画される）
5. 本番ビルド: `pnpm build` → `.next/standalone/` に `server.js` が出力される（App Service では `node server.js`）。全ページ `dynamic = "force-dynamic"` なので FastAPI 停止中でもビルドは通る（プラン 4.4）

## テスト

```
pnpm lint        # ESLint（eslint-config-next）
pnpm typecheck   # tsc --noEmit（初回や新ルート追加後は `pnpm exec next typegen` で PageProps 型を生成）
pnpm test        # Vitest（jsdom）。tests/**/*.test.{ts,tsx}
```

テストファイル名にはテスト設計書の ID を含める（例: `tests/ut-web-04.format.test.ts`）。

| テスト | 内容 |
| --- | --- |
| `ut-web-01.header` / `ut-web-01.cart-provider` | ヘッダーのバッジ。CartProvider にカート応答（item_count）を渡すと更新される |
| `ut-web-04.format` | `formatYen(6520) === "¥6,520"`、先頭が U+00A5 |
| `ut-web-05.env-validation` | 環境変数ローダー |
| `ut-web-08.purchase-panel` | 在庫 0 の色/サイズで追加ボタン disabled＋「在庫切れ」。固定バーの追従（UT-WEB-07） |
| `csrf-validation` | CSRF 判定（一致で通過・欠落/不一致で拒否）、`csrf_token` Cookie に HttpOnly が無いこと |
| `bff.cart-route` | `/api/cart*` ルート。fetch をモックし、`cart_token` が Cookie と違えば Set-Cookie、同じなら付かない。CSRF 無しは 403 で FastAPI に到達しない |
| `st-sec-07.cookie` / `bff.api-error-shape` / `cart-messages` | Cookie 属性・エラー本文の整形・文言 |

## ディレクトリ

```
app/
  layout.tsx                 共通レイアウト。Cookie の有無を CartProvider に渡す（Cookie 無しはカート取得を省く）
  page.tsx                   ホーム DS-SCR-001（トップ画像・性別カテゴリ・新着 8 件・お知らせ）
  products/page.tsx          商品一覧 DS-SCR-002（searchParams: gender・category・page。24 件区切り＋「もっと見る」）
  products/[id]/page.tsx     商品詳細 DS-SCR-003（画像・価格・色/サイズ/数量・説明・素材・関連。404 は notFound）
  cart/page.tsx              カート DS-SCR-004（Cookie があれば Server Component が初期表示を取得）
  not-found.tsx              404
  api/health/route.ts        BFF 疎通確認。FastAPI 未起動なら 503 {code:"upstream_unavailable"}
  api/cart/route.ts          GET: DS-API-010 取り次ぎ。cart_token・csrf_token Cookie の発行・更新
  api/cart/items/route.ts    POST: DS-API-011 取り次ぎ（CSRF 必須）
  api/cart/items/[id]/route.ts  PATCH/DELETE: DS-API-012/013 取り次ぎ（CSRF 必須）
  api/products/route.ts      GET: DS-API-002 取り次ぎ（「もっと見る」用）
components/
  Header.tsx / HeaderWithCart.tsx  ヘッダー（表示部品）と CartProvider への接続
  Footer.tsx
  CartProvider.tsx           カート点数の共有状態（useCart: itemCount・applyCart・refresh）
  Toast.tsx                  トースト（ToastProvider・useToast().show）
  ConfirmDialog.tsx          確認ダイアログ（role=dialog・Escape・Tab 循環・busy）
  ProductCard.tsx / Price.tsx / LoadError.tsx / CategoryNav.tsx
  ProductsGrid.tsx           一覧グリッド＋「もっと見る」（クライアント）
  PurchasePanel.tsx          詳細の色/サイズ/数量・追加・375px 下部固定バー（クライアント）
  CartView.tsx               カート明細・数量変更・削除（確認ダイアログ）・金額（クライアント）
lib/
  format.ts                  formatYen（半角 ¥ 固定）
  types.ts                   FastAPI 応答型（openapi.json と突き合わせ済み）
  image.ts                   imageUrl(base, image_path)
  gender.ts                  性別区分の表示名
  csrf-validation.ts         CSRF 判定（純粋関数）
  cart-messages.ts           エラー本文 → 利用者向け文言、在庫警告文
  cookie.ts                  Set-Cookie 組み立て（cart_token: HttpOnly／csrf_token: HttpOnly なし）
  env-validation.ts          validateEnv（純粋関数。UT-WEB-05）
  client/cart-api.ts         ブラウザ → BFF（X-CSRF-Token 付与。未発行なら GET /api/cart で発行させる）
  server/env.ts              `server-only`。process.env を validateEnv に渡すローダー
  server/api.ts              `server-only`。FastAPI 呼び出し（X-Internal-Token・エラー本文整形・no-store）
  server/csrf.ts             `server-only`。verifyCsrf(request) / issueCsrfCookieIfMissing(request)
  server/cart-proxy.ts       `server-only`。カート BFF 共通の取り次ぎ（X-Cart-Token・Set-Cookie）
  server/catalog.ts          `server-only`。Server Component 用のデータ取得（loadOrNull で失敗を吸収）
scripts/gen-placeholders.mjs 商品画像プレースホルダー生成
public/products/NNN/1.jpg    生成されたプレースホルダー（PNG バイナリ。拡張子は seed の image_path に合わせて .jpg）
tests/                       Vitest（setup.ts・stubs/server-only.ts）
```

## カート・CSRF の流れ（設計 7.3・DS-API-010〜013）

- **匿名カートトークンは FastAPI が発行する**。BFF は Cookie `cart_token` を `X-Cart-Token` ヘッダに載せて取り次ぎ、応答の `cart_token` が Cookie と違えば（Cookie 無し・未知トークン）`Set-Cookie` で更新する。属性は HttpOnly・SameSite=Lax・Path=/・Max-Age 90 日・Secure は production のみ。
- **CSRF は Double Submit Cookie**。`GET /api/cart` が Cookie `csrf_token`（HttpOnly なし・SameSite=Lax・32 バイト乱数 base64url）を未発行なら発行する。ブラウザは `document.cookie` から読んで `X-CSRF-Token` ヘッダに載せる。POST/PATCH/DELETE は `lib/server/csrf.ts` の `verifyCsrf(request)` で先に検証し、欠落・不一致は 403 `{code:"forbidden"}` で FastAPI へ到達させない。
- **Server Component は Cookie を発行できない**ので、Cookie 無しの訪問者にはバッジ 0 を描き、カート作成は最初の追加操作（`lib/client/cart-api.ts` の `ensureCsrfToken` → `GET /api/cart`）に任せる。
- FastAPI のエラー本文は `code` と設計 4.5 の詳細キー（`fields`・`items`・`field`・`limit` など）だけ通す（`sanitizeErrorBody`）。文言化は `lib/cart-messages.ts`。

### Wave 2（注文手続き）での使い方

```ts
// Route Handler（/api/checkout/prepare, /api/orders）
import { verifyCsrf } from "@/lib/server/csrf";
export async function POST(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied; // 403 forbidden
  // ... FastAPI へ取り次ぎ（apiFetch）。カート応答を返すなら proxyCartRequest を流用できる
}

// クライアント
import { ensureCsrfToken } from "@/lib/client/cart-api"; // 未発行なら GET /api/cart で発行
import { useToast } from "@/components/Toast";            // toast.show({ kind: "success" | "error", message, action? })
import ConfirmDialog from "@/components/ConfirmDialog";  // open / busy / destructive / onConfirm / onCancel
```

## デザイン基準（`docs/03_設計仕様書/付録_デザイン基準_v1.md`）

見た目の規則はキキ＆ララのデザイン基準 v1 が正本。根拠は `docs/03_設計仕様書/付録_GUサイト調査_20260918.md`。GU のロゴ画像・写真・文言・アイコン素材は使わない（ロゴはテキスト）。

### トークン（`app/globals.css`）

- Tailwind 4 の `@theme` に基準 2 章の値を定義。`--color-*`・`--radius-*`・`--shadow-*` は `initial` で既定値を消しているので、**`bg-gray-900` のような Tailwind パレットのクラスは使えない**（生成されない）。使えるのはトークン由来のクラスだけ。
- 色: `bg-bg`／`text-fg`／`text-fg-muted`／`border-line`／`bg-primary`＋`text-primary-fg`／`bg-accent`／`text-danger`／`text-success`／`bg-badge`／`bg-disabled-bg`＋`text-disabled-fg`／`bg-overlay`。薄い背景は `bg-line/40` のように不透明度修飾子で作る。
- 文字サイズ: `text-xs`(12)／`text-sm`(14)／`text-base`(16)／`text-lg`(20)／`text-xl`(24)／`text-2xl`(32)。行間は見出し系（xl・2xl）1.4、他 1.5。
- ウェイト: 見出し・商品名 `font-light`(300)、本文 `font-normal`(400)、価格・ボタン `font-bold`(700)。見出し・価格は `tracking-heading`(0.02em)。
- 角丸: `rounded-pill`（ボタン・チップ・バッジ）／`rounded-sm`（8px。画像・カード・入力欄）。影: `shadow-modal`（ConfirmDialog のみ）。
- 書体: `app/layout.tsx` が `next/font/google` の `Noto_Sans_JP`（300/400/700・`display: swap`）を `--font-noto-sans-jp` として `<html>` に付け、`globals.css` の `--font-body`／`--font-heading`（`font-body`／`font-heading`）が参照する。ビルド時に Google Fonts へ到達できる必要がある。
- 寸法: 主要 CTA `h-13`(52px)、タッチターゲット `h-11`/`size-11`(44px)、ページ幅 `max-w-page`(1280px)、商品グリッドの列間 `gap-x-2`(8px)・縦 `gap-y-6`(24px)。
- フォーカス: `:focus-visible` に共通 outline（2px `--color-fg`・offset 2px）を `@layer base` で当てているので、部品側で `focus-visible:*` を書く必要はない（暗い背景上だけ `focus-visible:outline-bg`）。

### 共通部品の使い方（Wave 2 の SCR-005／006 も同じ部品を使う）

```tsx
import Button, { buttonClass } from "@/components/Button";
<Button variant="primary" size="lg" full busy={submitting} busyLabel="送信中…" onClick={...}>確認画面へ</Button>
// variant: primary | secondary | ghost | danger ／ size: lg(52px) | md(44px) ／ busy 中は disabled＋aria-busy＋ラベル差し替え
<Link href="/" className={buttonClass({ variant: "secondary", size: "lg" })}>買い物を続ける</Link>

import { TextField, SelectField, controlClass } from "@/components/Form";
<TextField id="name" label="氏名" required error={errors.name} hint="全角" value={...} onChange={...} />
<SelectField id="pref" label="都道府県" required error={errors.pref}>{options}</SelectField>
// ラベルは上、必須は「（必須）」テキスト、error があると枠線 danger＋直下に role="alert"、aria-invalid / aria-describedby を自動付与
<select className={controlClass} aria-label="数量">…</select> // ラベルを別に持つ場合は見た目だけ流用

import Breadcrumb from "@/components/Breadcrumb";
<Breadcrumb items={[{ label: "ホーム", href: "/" }, { label: "カート", href: "/cart" }, { label: "注文手続き" }]} />

import { useToast } from "@/components/Toast";          // show({ kind: "success" | "error" | "info", message, action?, durationMs? })
import ConfirmDialog from "@/components/ConfirmDialog";  // open / title / description / confirmLabel / destructive / busy / onConfirm / onCancel
// 警告文: <p role="alert" className="text-sm font-bold text-danger">⚠ …</p>
// 金額サマリのボックス: <aside className="rounded-sm border border-line bg-line/40 p-4 text-sm">（CartView と同じ）
```

## 秘密情報の取り扱い（設計 7.2）

- 秘密を触るモジュールは `lib/server/` に置き、先頭で `import "server-only"` する。クライアントコンポーネント（`"use client"`）から import すると `pnpm build` が失敗する（Wave 0 で実証済み）。
- `IMAGE_BASE_URL` は公開 URL なので Server Component から props でクライアントへ渡してよい。`INTERNAL_TOKEN`・`API_BASE_URL` は渡さない。

## BFF の手動確認（curl）

```
curl -i -c jar.txt http://localhost:3000/api/cart
#   Set-Cookie: cart_token=...; Path=/; Max-Age=7776000; HttpOnly; SameSite=Lax
#   Set-Cookie: csrf_token=...; Path=/; Max-Age=7776000; SameSite=Lax
curl -i -b jar.txt -X POST -H "Content-Type: application/json" -d '{"variant_id":1,"quantity":1}' http://localhost:3000/api/cart/items
#   403 {"code":"forbidden"}（X-CSRF-Token 無し）
curl -i -b jar.txt -X POST -H "Content-Type: application/json" -H "X-CSRF-Token: <jar.txt の csrf_token>" -d '{"variant_id":1,"quantity":1}' http://localhost:3000/api/cart/items
#   201 カート応答
curl -i http://localhost:3000/api/health   # FastAPI 未起動: 503 {"code":"upstream_unavailable"}
```
