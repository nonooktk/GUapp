import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { UpstreamCart } from "@/lib/server/cart-proxy";

// セキュリティ強化 S3（web 側）・S4: カート応答の cart_token の扱い。
//  S3: FastAPI が cart_token=null（カート未作成の GET /cart）を返したら、cart_token の Set-Cookie を出さない。csrf_token は従来どおり。
//  S4: ブラウザへ返す本文から cart_token を除く（Set-Cookie は除く前の値で処理）。
process.env.API_BASE_URL = "http://fastapi.test:8000";
process.env.INTERNAL_TOKEN = "dummy-internal-token"; // gitleaks:allow（テスト用ダミー）
process.env.IMAGE_BASE_URL = "http://localhost:3000";
process.env.APP_ENV = "development";
process.env.SESSION_COOKIE_DOMAIN = "";

const CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret
const TOKEN_A = "cartTokenAAAA_-0123456789abcdefghijklmnopq"; // gitleaks:allow // pragma: allowlist secret
const TOKEN_B = "cartTokenBBBB_-0123456789abcdefghijklmnopq"; // gitleaks:allow // pragma: allowlist secret

function cart(token: string | null): UpstreamCart {
  return {
    cart_token: token,
    items: [],
    item_count: 0,
    subtotal: 0,
    shipping_fee: 550,
    total: 550,
    free_shipping_threshold: 4990,
    can_checkout: false,
  };
}
const upstream = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });
const authed = { cookie: `cart_token=${TOKEN_A}; csrf_token=${CSRF}`, "X-CSRF-Token": CSRF, "Content-Type": "application/json" };

let GET: typeof import("@/app/api/cart/route").GET;
let POST: typeof import("@/app/api/cart/items/route").POST;
let PATCH: typeof import("@/app/api/cart/items/[id]/route").PATCH;
let DELETE: typeof import("@/app/api/cart/items/[id]/route").DELETE;
let PREPARE: typeof import("@/app/api/checkout/prepare/route").POST;
let stripCartToken: typeof import("@/lib/server/cart-proxy").stripCartToken;

beforeAll(async () => {
  ({ GET } = await import("@/app/api/cart/route"));
  ({ POST } = await import("@/app/api/cart/items/route"));
  ({ PATCH, DELETE } = await import("@/app/api/cart/items/[id]/route"));
  ({ POST: PREPARE } = await import("@/app/api/checkout/prepare/route"));
  ({ stripCartToken } = await import("@/lib/server/cart-proxy"));
});

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("S3 cart_token が null のとき", () => {
  it("GET /api/cart（Cookie 無し）: cart_token の Set-Cookie を出さず、csrf_token は発行する", async () => {
    fetchMock.mockResolvedValue(upstream(200, cart(null)));
    const res = await GET(new Request("http://localhost:3000/api/cart"));
    expect(res.status).toBe(200);
    const cookies = res.headers.getSetCookie();
    expect(cookies.some((c) => c.startsWith("cart_token="))).toBe(false);
    expect(cookies.some((c) => c.startsWith("csrf_token=") && !c.includes("HttpOnly"))).toBe(true);
    const json = await res.json();
    expect(json).toMatchObject({ items: [], item_count: 0, can_checkout: false });
    expect(json).not.toHaveProperty("cart_token");
  });

  it("GET /api/cart（未知の Cookie）: cart_token の Set-Cookie を出さない。csrf_token が発行済みなら Set-Cookie は 0 件", async () => {
    fetchMock.mockResolvedValue(upstream(200, cart(null)));
    const res = await GET(
      new Request("http://localhost:3000/api/cart", { headers: { cookie: `cart_token=${TOKEN_B}; csrf_token=${CSRF}` } }),
    );
    expect(res.headers.getSetCookie()).toEqual([]);
  });
});

describe("S3 従来の Set-Cookie は維持する", () => {
  it("POST /api/cart/items で FastAPI が新しい cart_token を返したら cart_token を Set-Cookie（HttpOnly）", async () => {
    fetchMock.mockResolvedValue(upstream(201, cart(TOKEN_B)));
    const res = await POST(
      new Request("http://localhost:3000/api/cart/items", {
        method: "POST",
        body: JSON.stringify({ variant_id: 1, quantity: 1 }),
        headers: { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF },
      }),
    );
    expect(res.status).toBe(201);
    const cookies = res.headers.getSetCookie();
    expect(cookies).toHaveLength(1);
    expect(cookies[0]).toMatch(new RegExp(`^cart_token=${TOKEN_B}; Path=/; Max-Age=7776000; HttpOnly; SameSite=Lax$`));
  });

  it("Cookie と同じ cart_token なら Set-Cookie を出さない", async () => {
    fetchMock.mockResolvedValue(upstream(200, cart(TOKEN_A)));
    const res = await GET(new Request("http://localhost:3000/api/cart", { headers: { cookie: authed.cookie } }));
    expect(res.headers.getSetCookie()).toEqual([]);
  });

  it("Cookie 無しで cart_token と csrf_token の両方を出す（GET に cart_token が付く従来の API でも）", async () => {
    fetchMock.mockResolvedValue(upstream(200, cart(TOKEN_A)));
    const res = await GET(new Request("http://localhost:3000/api/cart"));
    const cookies = res.headers.getSetCookie();
    expect(cookies.some((c) => c.startsWith(`cart_token=${TOKEN_A}`))).toBe(true);
    expect(cookies.some((c) => c.startsWith("csrf_token="))).toBe(true);
  });
});

describe("S4 応答本文に cart_token が無い", () => {
  it("GET・POST・PATCH・DELETE のどれでも、FastAPI が返した cart_token は本文に出ない", async () => {
    fetchMock.mockImplementation(async () => upstream(200, cart(TOKEN_B)));

    const get = await GET(new Request("http://localhost:3000/api/cart"));
    const post = await POST(
      new Request("http://localhost:3000/api/cart/items", {
        method: "POST",
        body: JSON.stringify({ variant_id: 1, quantity: 1 }),
        headers: authed,
      }),
    );
    const patch = await PATCH(
      new Request("http://localhost:3000/api/cart/items/7", {
        method: "PATCH",
        body: JSON.stringify({ quantity: 2 }),
        headers: authed,
      }),
      ctx("7"),
    );
    const del = await DELETE(new Request("http://localhost:3000/api/cart/items/7", { method: "DELETE", headers: authed }), ctx("7"));

    for (const res of [get, post, patch, del]) {
      const text = await res.clone().text();
      expect(text).not.toContain("cart_token");
      expect(text).not.toContain(TOKEN_B);
      expect(JSON.parse(text)).toMatchObject({ item_count: 0, total: 550 });
    }
    // Set-Cookie は除く前の値で処理されている（Cookie は TOKEN_A、応答は TOKEN_B なので更新される）
    expect(patch.headers.getSetCookie().some((c) => c.startsWith(`cart_token=${TOKEN_B}`))).toBe(true);
  });

  it("POST /api/checkout/prepare も、万一 cart_token が入っていても本文から除く", async () => {
    fetchMock.mockResolvedValue(upstream(200, { idempotency_key: "k", items: [], total: 0, cart_token: TOKEN_B }));
    const res = await PREPARE(new Request("http://localhost:3000/api/checkout/prepare", { method: "POST", headers: authed }));
    const text = await res.text();
    expect(text).not.toContain("cart_token");
    expect(JSON.parse(text)).toMatchObject({ idempotency_key: "k" });
  });

  it("stripCartToken: 最上位の cart_token だけ除き、他の項目・配列・null はそのまま", () => {
    expect(stripCartToken({ cart_token: "x", items: [{ cart_token: "inner" }], total: 1 })).toEqual({
      items: [{ cart_token: "inner" }],
      total: 1,
    });
    expect(stripCartToken(null)).toBeNull();
    expect(stripCartToken([1, 2])).toEqual([1, 2]);
    expect(stripCartToken({ a: 1 })).toEqual({ a: 1 });
  });
});
