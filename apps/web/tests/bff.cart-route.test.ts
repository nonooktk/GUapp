import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Cart } from "@/lib/types";

// BFF カートルート（DS-API-010〜013 取り次ぎ・設計仕様書 4.3・7.3）。FastAPI は fetch をモックして差し替える。
// getEnv() は初回呼び出しで process.env を読むため、import より前に env を用意する。
process.env.API_BASE_URL = "http://fastapi.test:8000";
process.env.INTERNAL_TOKEN = "dummy-internal-token"; // gitleaks:allow（テスト用ダミー）
process.env.IMAGE_BASE_URL = "http://localhost:3000";
process.env.APP_ENV = "development";
process.env.SESSION_COOKIE_DOMAIN = "";

const CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret
const CART_TOKEN_A = "cartTokenAAAA_-0123456789abcdefghijklmnopq"; // gitleaks:allow // pragma: allowlist secret
const CART_TOKEN_B = "cartTokenBBBB_-0123456789abcdefghijklmnopq"; // gitleaks:allow // pragma: allowlist secret

function cart(token: string, itemCount = 0): Cart {
  return {
    cart_token: token,
    items: [],
    item_count: itemCount,
    subtotal: 0,
    shipping_fee: 550,
    total: 550,
    free_shipping_threshold: 4990,
    can_checkout: false,
  };
}

function upstream(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let GET: typeof import("@/app/api/cart/route").GET;
let POST: typeof import("@/app/api/cart/items/route").POST;
let PATCH: typeof import("@/app/api/cart/items/[id]/route").PATCH;
let DELETE: typeof import("@/app/api/cart/items/[id]/route").DELETE;

beforeAll(async () => {
  ({ GET } = await import("@/app/api/cart/route"));
  ({ POST } = await import("@/app/api/cart/items/route"));
  ({ PATCH, DELETE } = await import("@/app/api/cart/items/[id]/route"));
});

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

const setCookies = (res: Response) => res.headers.getSetCookie();

describe("GET /api/cart", () => {
  it("Cookie 無し: FastAPI が発行した cart_token と csrf_token の両方を Set-Cookie する", async () => {
    fetchMock.mockResolvedValue(upstream(200, cart(CART_TOKEN_A)));
    const res = await GET(new Request("http://localhost:3000/api/cart"));

    expect(res.status).toBe(200);
    const cookies = setCookies(res);
    expect(cookies.some((c) => c.startsWith(`cart_token=${CART_TOKEN_A}`) && c.includes("HttpOnly"))).toBe(true);
    expect(cookies.some((c) => c.startsWith("csrf_token=") && !c.includes("HttpOnly"))).toBe(true);
    expect(await res.json()).toMatchObject({ cart_token: CART_TOKEN_A, item_count: 0 });

    // FastAPI へは X-Internal-Token 付き・X-Cart-Token 無しで /api/v1/cart を呼ぶ
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://fastapi.test:8000/api/v1/cart");
    const h = new Headers(init.headers);
    expect(h.get("X-Internal-Token")).toBe("dummy-internal-token");
    expect(h.get("X-Cart-Token")).toBeNull();
    expect(init.cache).toBe("no-store");
  });

  it("Cookie と応答の cart_token が同じなら cart_token の Set-Cookie は付かない", async () => {
    fetchMock.mockResolvedValue(upstream(200, cart(CART_TOKEN_A, 2)));
    const res = await GET(
      new Request("http://localhost:3000/api/cart", {
        headers: { cookie: `cart_token=${CART_TOKEN_A}; csrf_token=${CSRF}` },
      }),
    );
    expect(res.status).toBe(200);
    expect(setCookies(res)).toEqual([]);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("X-Cart-Token")).toBe(CART_TOKEN_A);
  });

  it("Cookie と応答の cart_token が違えば（未知トークン→再発行）cart_token を Set-Cookie で更新する", async () => {
    fetchMock.mockResolvedValue(upstream(200, cart(CART_TOKEN_B)));
    const res = await GET(
      new Request("http://localhost:3000/api/cart", {
        headers: { cookie: `cart_token=${CART_TOKEN_A}; csrf_token=${CSRF}` },
      }),
    );
    const cookies = setCookies(res);
    expect(cookies).toHaveLength(1);
    expect(cookies[0]).toMatch(new RegExp(`^cart_token=${CART_TOKEN_B}; Path=/; Max-Age=7776000; HttpOnly; SameSite=Lax$`));
  });

  it("FastAPI に接続できなければ 503 upstream_unavailable", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const res = await GET(new Request("http://localhost:3000/api/cart"));
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ code: "upstream_unavailable" });
  });
});

describe("POST /api/cart/items（CSRF）", () => {
  const url = "http://localhost:3000/api/cart/items";
  const body = JSON.stringify({ variant_id: 1, quantity: 2 });

  it("CSRF ヘッダ無し → 403 forbidden。FastAPI を呼ばない", async () => {
    const res = await POST(
      new Request(url, { method: "POST", body, headers: { cookie: `cart_token=${CART_TOKEN_A}; csrf_token=${CSRF}` } }),
    );
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ code: "forbidden" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("CSRF ヘッダと Cookie が不一致 → 403。Cookie 無しでヘッダだけ → 403", async () => {
    const mismatch = await POST(
      new Request(url, {
        method: "POST",
        body,
        headers: { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF.slice(0, -1) + "Z" },
      }),
    );
    expect(mismatch.status).toBe(403);
    const noCookie = await POST(new Request(url, { method: "POST", body, headers: { "X-CSRF-Token": CSRF } }));
    expect(noCookie.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("CSRF 一致 → FastAPI へ取り次ぎ、201 とカート応答を返す", async () => {
    fetchMock.mockResolvedValue(upstream(201, cart(CART_TOKEN_A, 2)));
    const res = await POST(
      new Request(url, {
        method: "POST",
        body,
        headers: {
          cookie: `cart_token=${CART_TOKEN_A}; csrf_token=${CSRF}`,
          "X-CSRF-Token": CSRF,
          "Content-Type": "application/json",
        },
      }),
    );
    expect(res.status).toBe(201);
    expect(await res.json()).toMatchObject({ item_count: 2 });
    const [calledUrl, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toBe("http://fastapi.test:8000/api/v1/cart/items"); // gitleaks:allow（テスト用 URL。generic-api-key の誤検出）
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ variant_id: 1, quantity: 2 });
  });

  it("FastAPI の 409 out_of_stock は code と items だけ通す", async () => {
    fetchMock.mockResolvedValue(
      upstream(409, { code: "out_of_stock", items: [{ variant_id: 1 }], detail: "SELECT * FROM variants" }),
    );
    const res = await POST(
      new Request(url, {
        method: "POST",
        body,
        headers: { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF, "Content-Type": "application/json" },
      }),
    );
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ code: "out_of_stock", items: [{ variant_id: 1 }] });
  });

  it("quantity が整数でない・0 以下は 400 validation_error（FastAPI を呼ばない）", async () => {
    const res = await POST(
      new Request(url, {
        method: "POST",
        body: JSON.stringify({ variant_id: 1, quantity: 0 }),
        headers: { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF },
      }),
    );
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ code: "validation_error", fields: [{ name: "quantity", reason: "out_of_range" }] });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("PATCH / DELETE /api/cart/items/[id]", () => {
  const ctx = (id: string) => ({ params: Promise.resolve({ id }) });
  const okHeaders = { cookie: `cart_token=${CART_TOKEN_A}; csrf_token=${CSRF}`, "X-CSRF-Token": CSRF };

  it("PATCH: CSRF 無しは 403、一致すれば取り次ぐ", async () => {
    const denied = await PATCH(
      new Request("http://localhost:3000/api/cart/items/7", { method: "PATCH", body: JSON.stringify({ quantity: 3 }) }),
      ctx("7"),
    );
    expect(denied.status).toBe(403);

    fetchMock.mockResolvedValue(upstream(200, cart(CART_TOKEN_A, 3)));
    const ok = await PATCH(
      new Request("http://localhost:3000/api/cart/items/7", {
        method: "PATCH",
        body: JSON.stringify({ quantity: 3 }),
        headers: okHeaders,
      }),
      ctx("7"),
    );
    expect(ok.status).toBe(200);
    const [calledUrl, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toBe("http://fastapi.test:8000/api/v1/cart/items/7"); // gitleaks:allow（テスト用 URL。generic-api-key の誤検出）
    expect(init.method).toBe("PATCH");
  });

  it("DELETE: 一致すれば取り次ぎ、item_id が数字でなければ 404", async () => {
    fetchMock.mockResolvedValue(upstream(200, cart(CART_TOKEN_A, 0)));
    const ok = await DELETE(
      new Request("http://localhost:3000/api/cart/items/7", { method: "DELETE", headers: okHeaders }),
      ctx("7"),
    );
    expect(ok.status).toBe(200);
    expect((fetchMock.mock.calls[0] as [string, RequestInit])[1].method).toBe("DELETE");

    const bad = await DELETE(
      new Request("http://localhost:3000/api/cart/items/abc", { method: "DELETE", headers: okHeaders }),
      ctx("abc"),
    );
    expect(bad.status).toBe(404);
  });
});
