import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { OrderResponse, PrepareResponse } from "@/lib/types";

// テスト設計書 IT-BFF-01（CSRF 付きで内部認証ヘッダを付与して取り次ぎ 201）・IT-BFF-02（CSRF 無しは 403 で FastAPI へ到達しない）。
// 設計仕様書 4.3・7.2・7.3。FastAPI は fetch をモックして差し替える。getEnv() は初回に process.env を読むので import 前に用意する
process.env.API_BASE_URL = "http://fastapi.test:8000";
process.env.INTERNAL_TOKEN = "dummy-internal-token"; // gitleaks:allow // pragma: allowlist secret（テスト用ダミー）
process.env.IMAGE_BASE_URL = "http://localhost:3000";
process.env.APP_ENV = "development";
process.env.SESSION_COOKIE_DOMAIN = "";

const CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret
const CART_TOKEN = "cartTokenAAAA_-0123456789abcdefghijklmnopq"; // gitleaks:allow // pragma: allowlist secret
const IDEM_KEY = "idemKey_-0123456789abcdefghijklmnopqrstuvwx"; // gitleaks:allow // pragma: allowlist secret

const shipping = {
  ship_name: "テスト 太郎",
  ship_postal_code: "1000001",
  ship_address: "東京都　千代田区　千代田1-1　テストビル 101",
  ship_phone: "09012345678",
  guest_email: "test@example.com",
};

const orderBody = {
  idempotency_key: IDEM_KEY,
  ...shipping,
  receive_method: "delivery",
  payment_method: "card",
  display: { subtotal: 3980, shipping_fee: 550, total: 4530 },
};

const orderOut: OrderResponse = {
  order_number: "GU-260918-7K3M9Q2X",
  status: "accepted",
  items: [{ product_name: "テスト T", color: "黒", size: "M", unit_price: 1990, quantity: 2, line_total: 3980 }],
  subtotal: 3980,
  shipping_fee: 550,
  total: 4530,
  tax_included: 411,
  tax_rate: "0.10",
  ...shipping,
  receive_method: "delivery",
  payment_method: "card",
  ordered_at: "2026-09-18T03:04:05Z",
};

const prepareOut: PrepareResponse = {
  idempotency_key: IDEM_KEY,
  items: [],
  subtotal: 3980,
  shipping_fee: 550,
  total: 4530,
  tax_included: 411,
  tax_rate: "0.10",
  free_shipping_threshold: 4990,
};

function upstream(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

let POST_ORDERS: typeof import("@/app/api/orders/route").POST;
let POST_PREPARE: typeof import("@/app/api/checkout/prepare/route").POST;
let POST_LOOKUP: typeof import("@/app/api/orders/[orderNumber]/lookup/route").POST;

beforeAll(async () => {
  ({ POST: POST_ORDERS } = await import("@/app/api/orders/route"));
  ({ POST: POST_PREPARE } = await import("@/app/api/checkout/prepare/route"));
  ({ POST: POST_LOOKUP } = await import("@/app/api/orders/[orderNumber]/lookup/route"));
});

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

const okHeaders = {
  cookie: `cart_token=${CART_TOKEN}; csrf_token=${CSRF}`,
  "X-CSRF-Token": CSRF,
  "Content-Type": "application/json",
};

describe("IT-BFF-01 POST /api/orders（CSRF 付き）", () => {
  it("X-Internal-Token・X-Cart-Token・X-Forwarded-For を付けて FastAPI /api/v1/orders へ取り次ぎ、201 の本文をそのまま返す", async () => {
    fetchMock.mockResolvedValue(upstream(201, orderOut));
    const res = await POST_ORDERS(
      new Request("http://localhost:3000/api/orders", {
        method: "POST",
        body: JSON.stringify(orderBody),
        headers: { ...okHeaders, "x-forwarded-for": "203.0.113.9, 10.0.0.1" },
      }),
    );

    expect(res.status).toBe(201);
    expect(await res.json()).toEqual(orderOut);
    expect(res.headers.get("Cache-Control")).toBe("no-store");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://fastapi.test:8000/api/v1/orders"); // gitleaks:allow（テスト用 URL）
    expect(init.method).toBe("POST");
    const h = new Headers(init.headers);
    expect(h.get("X-Internal-Token")).toBe("dummy-internal-token");
    expect(h.get("X-Cart-Token")).toBe(CART_TOKEN);
    expect(h.get("X-Forwarded-For")).toBe("203.0.113.9");
    expect(JSON.parse(init.body as string)).toEqual(orderBody);
  });

  it("x-forwarded-for が無ければ X-Forwarded-For は 127.0.0.1（空にしない）", async () => {
    fetchMock.mockResolvedValue(upstream(200, orderOut));
    const res = await POST_ORDERS(new Request("http://localhost:3000/api/orders", { method: "POST", body: JSON.stringify(orderBody), headers: okHeaders }));
    expect(res.status).toBe(200); // 同じキーの再送は 200 で既存注文
    const h = new Headers((fetchMock.mock.calls[0] as [string, RequestInit])[1].headers);
    expect(h.get("X-Forwarded-For")).toBe("127.0.0.1");
  });

  it("本文の余計なキーは落とし、設計 4.4 の項目だけ転送する。必須が欠ければ FastAPI を呼ばず 400", async () => {
    fetchMock.mockResolvedValue(upstream(201, orderOut));
    await POST_ORDERS(
      new Request("http://localhost:3000/api/orders", {
        method: "POST",
        body: JSON.stringify({ ...orderBody, cart_id: 1, is_admin: true }),
        headers: okHeaders,
      }),
    );
    expect(JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string)).toEqual(orderBody);

    fetchMock.mockReset();
    const { display: _display, ...noDisplay } = orderBody;
    void _display;
    const bad = await POST_ORDERS(
      new Request("http://localhost:3000/api/orders", { method: "POST", body: JSON.stringify(noDisplay), headers: okHeaders }),
    );
    expect(bad.status).toBe(400);
    expect(await bad.json()).toEqual({ code: "validation_error", fields: [{ name: "display", reason: "format" }] });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("FastAPI の 409 price_changed は code と amounts だけ通す（内部情報は落とす）", async () => {
    fetchMock.mockResolvedValue(
      upstream(409, { code: "price_changed", amounts: { subtotal: 3980, shipping_fee: 550, total: 4530 }, sql: "SELECT 1", trace: "x" }),
    );
    const res = await POST_ORDERS(new Request("http://localhost:3000/api/orders", { method: "POST", body: JSON.stringify(orderBody), headers: okHeaders }));
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ code: "price_changed", amounts: { subtotal: 3980, shipping_fee: 550, total: 4530 } });
  });

  it("FastAPI に接続できなければ 503 upstream_unavailable", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const res = await POST_ORDERS(new Request("http://localhost:3000/api/orders", { method: "POST", body: JSON.stringify(orderBody), headers: okHeaders }));
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ code: "upstream_unavailable" });
  });
});

describe("IT-BFF-02 CSRF 無し → 403、FastAPI へ到達しない", () => {
  it("POST /api/orders: ヘッダ無し／不一致／Cookie 無し", async () => {
    const url = "http://localhost:3000/api/orders";
    const body = JSON.stringify(orderBody);
    const noHeader = await POST_ORDERS(new Request(url, { method: "POST", body, headers: { cookie: `cart_token=${CART_TOKEN}; csrf_token=${CSRF}` } }));
    expect(noHeader.status).toBe(403);
    expect(await noHeader.json()).toEqual({ code: "forbidden" });

    const mismatch = await POST_ORDERS(
      new Request(url, { method: "POST", body, headers: { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF.slice(0, -1) + "Z" } }),
    );
    expect(mismatch.status).toBe(403);

    const noCookie = await POST_ORDERS(new Request(url, { method: "POST", body, headers: { "X-CSRF-Token": CSRF } }));
    expect(noCookie.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("POST /api/checkout/prepare・/api/orders/[n]/lookup も同じ", async () => {
    const prep = await POST_PREPARE(new Request("http://localhost:3000/api/checkout/prepare", { method: "POST" }));
    expect(prep.status).toBe(403);
    const look = await POST_LOOKUP(
      new Request("http://localhost:3000/api/orders/GU-260918-7K3M9Q2X/lookup", { method: "POST", body: JSON.stringify({ guest_email: "test@example.com" }) }),
      { params: Promise.resolve({ orderNumber: "GU-260918-7K3M9Q2X" }) },
    );
    expect(look.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("POST /api/checkout/prepare", () => {
  it("CSRF 一致 → FastAPI /checkout/prepare へ X-Cart-Token 付きで取り次ぎ、200 の本文を返す", async () => {
    fetchMock.mockResolvedValue(upstream(200, prepareOut));
    const res = await POST_PREPARE(new Request("http://localhost:3000/api/checkout/prepare", { method: "POST", headers: okHeaders }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(prepareOut);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://fastapi.test:8000/api/v1/checkout/prepare"); // gitleaks:allow（テスト用 URL）
    expect(new Headers(init.headers).get("X-Cart-Token")).toBe(CART_TOKEN);
  });

  it("409 out_of_stock は code と items を通す", async () => {
    fetchMock.mockResolvedValue(upstream(409, { code: "out_of_stock", items: [3], detail: "internal" }));
    const res = await POST_PREPARE(new Request("http://localhost:3000/api/checkout/prepare", { method: "POST", headers: okHeaders }));
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ code: "out_of_stock", items: [3] });
  });
});

describe("POST /api/orders/[orderNumber]/lookup", () => {
  const ctx = (orderNumber: string) => ({ params: Promise.resolve({ orderNumber }) });
  const lookupBody = JSON.stringify({ guest_email: "test@example.com" });

  it("形式の正しい番号は FastAPI へ取り次ぎ 200。X-Forwarded-For を付ける", async () => {
    fetchMock.mockResolvedValue(upstream(200, orderOut));
    const res = await POST_LOOKUP(
      new Request("http://localhost:3000/api/orders/GU-260918-7K3M9Q2X/lookup", {
        method: "POST",
        body: lookupBody,
        headers: { ...okHeaders, "x-forwarded-for": "198.51.100.7" },
      }),
      ctx("GU-260918-7K3M9Q2X"),
    );
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(orderOut);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://fastapi.test:8000/api/v1/orders/GU-260918-7K3M9Q2X/lookup"); // gitleaks:allow（テスト用 URL）
    expect(new Headers(init.headers).get("X-Forwarded-For")).toBe("198.51.100.7");
    expect(JSON.parse(init.body as string)).toEqual({ guest_email: "test@example.com" });
  });

  it("番号の形式が違えば FastAPI を呼ばず 404（存在を区別しない）", async () => {
    const res = await POST_LOOKUP(
      new Request("http://localhost:3000/api/orders/abc/lookup", { method: "POST", body: lookupBody, headers: okHeaders }),
      ctx("abc"),
    );
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ code: "not_found" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("429 rate_limited は Retry-After ヘッダを透過する（ST-F025-03 の土台）", async () => {
    fetchMock.mockResolvedValue(upstream(429, { code: "rate_limited" }, { "Retry-After": "1800" }));
    const res = await POST_LOOKUP(
      new Request("http://localhost:3000/api/orders/GU-260918-7K3M9Q2X/lookup", { method: "POST", body: lookupBody, headers: okHeaders }),
      ctx("GU-260918-7K3M9Q2X"),
    );
    expect(res.status).toBe(429);
    expect(res.headers.get("Retry-After")).toBe("1800");
    expect(await res.json()).toEqual({ code: "rate_limited" });
  });
});
