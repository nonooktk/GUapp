import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// テスト設計書 UT-WEB-52（ルートレイアウトの分離。DS-DEC-122）。x-admin-area が "1" のときだけ顧客向けの枠を省く

let requestHeaders: Record<string, string> = {};
let cookieJar: Record<string, string> = {};
vi.mock("next/headers", () => ({
  headers: async () => new Headers(requestHeaders),
  cookies: async () => ({
    get: (name: string) => (name in cookieJar ? { name, value: cookieJar[name] } : undefined),
    has: (name: string) => name in cookieJar,
  }),
}));
vi.mock("next/font/google", () => ({ Noto_Sans_JP: () => ({ variable: "font-noto" }) }));
const getCategories = vi.fn(async () => ({ categories: [] }));
vi.mock("@/lib/server/catalog", () => ({
  getCategories: () => getCategories(),
  loadOrNull: async (p: Promise<unknown>) => p,
  getImageBaseUrl: () => "http://localhost:8000/images",
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/",
}));
vi.mock("@/app/globals.css", () => ({}));

const ORIGINAL_DEMO = process.env.DEMO_PUBLIC_UNTIL;
beforeEach(() => {
  requestHeaders = {};
  cookieJar = {};
  getCategories.mockClear();
  process.env.DEMO_PUBLIC_UNTIL = "2026-12-31";
});
afterEach(() => {
  if (ORIGINAL_DEMO === undefined) delete process.env.DEMO_PUBLIC_UNTIL;
  else process.env.DEMO_PUBLIC_UNTIL = ORIGINAL_DEMO;
});

async function render(): Promise<string> {
  const { default: RootLayout } = await import("@/app/layout");
  const element = await RootLayout({ children: <p id="page-body">本文</p> } as never);
  return renderToStaticMarkup(element);
}

describe("UT-WEB-52 ルートレイアウトの分離", () => {
  it("x-admin-area: 1 のとき顧客向けのヘッダー・フッター・カート・期間限定公開の帯を省き、カテゴリを取得しない。本文は出す", async () => {
    requestHeaders = { "x-admin-area": "1" };
    const html = await render();
    expect(html).toContain('id="page-body"');
    expect(html).not.toContain("<header");
    expect(html).not.toContain("<footer");
    expect(html).not.toContain("カート");
    expect(html).not.toContain("GU ホーム");
    expect(html).not.toContain("期間限定で公開");
    expect(html).not.toContain('id="main"'); // main は /admin のレイアウト側が出す
    // F-029: 管理画面には AI アシスタントのボタンもパネルも出さない
    expect(html).not.toContain("AI アシスタントに相談する");
    expect(getCategories).not.toHaveBeenCalled();
    expect(html).toContain('lang="ja"');
  });

  it("ヘッダーが無いとき顧客向けの枠を出す（従来どおり）。カテゴリを取得する", async () => {
    const html = await render();
    expect(html).toContain("<header");
    expect(html).toContain("<footer");
    expect(html).toContain("期間限定で公開");
    expect(html).toContain('id="main"');
    expect(html).toContain('id="page-body"');
    expect(html).toContain("AI アシスタントに相談する"); // F-029: 顧客向けの枠にはチャットのボタンを出す
    expect(getCategories).toHaveBeenCalledTimes(1);
  });

  it.each([["0"], ["true"], ["yes"], ["11"], [""]])("x-admin-area が %j のときは顧客向けの枠を出す", async (value) => {
    requestHeaders = { "x-admin-area": value };
    const html = await render();
    expect(html).toContain("<header");
    expect(html).toContain("<footer");
  });

  it("会員のログイン状態(Cookie sid)は顧客向けの枠のときだけ見る。管理画面の枠では参照しない", async () => {
    cookieJar = { sid: "x".repeat(43) };
    const customer = await render();
    expect(customer).toContain('aria-label="マイページ"');
    requestHeaders = { "x-admin-area": "1" };
    const admin = await render();
    expect(admin).not.toContain("マイページ");
  });
});
