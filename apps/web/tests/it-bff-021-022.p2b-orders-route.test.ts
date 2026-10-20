import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { callOf, CART_TOKEN, csrfHeaders, jsonPost, SID_OLD, upstream } from "./helpers/bff";

// テスト設計書 IT-BFF-021（POST /api/checkout/prepare の receive_method）・IT-BFF-022（POST /api/orders の store_code・X-Session-Token）。
// 設計仕様書 4.4・4.7・DS-PRC-021a・014-3。

let PREPARE: (request: Request) => Promise<Response>;
let ORDERS: (request: Request) => Promise<Response>;
beforeAll(async () => {
  ({ POST: PREPARE } = await import("@/app/api/checkout/prepare/route"));
  ({ POST: ORDERS } = await import("@/app/api/orders/route"));
});

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

const IDEM = "idemKey_-0123456789abcdefghijklmnopqrstuvwx"; // gitleaks:allow // pragma: allowlist secret
const prepareOut = { idempotency_key: IDEM, receive_method: "store", items: [], subtotal: 3980, shipping_fee: 0, total: 3980, tax_included: 361, tax_rate: "0.10", free_shipping_threshold: 4990 };
const cartHeaders = (extra = "") => csrfHeaders(`cart_token=${CART_TOKEN}${extra ? `; ${extra}` : ""}`);

describe("IT-BFF-021 POST /api/checkout/prepare", () => {
  it("receive_method=store はそのまま FastAPI に渡る（X-Cart-Token つき）", async () => {
    fetchMock.mockResolvedValue(upstream(200, prepareOut));
    const res = await PREPARE(jsonPost("/api/checkout/prepare", { receive_method: "store" }, cartHeaders()));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(prepareOut);
    const c = callOf(fetchMock);
    expect(c.url).toBe("http://fastapi.test:8000/api/v1/checkout/prepare"); // gitleaks:allow（テスト用 URL）
    expect(c.headers.get("X-Cart-Token")).toBe(CART_TOKEN);
    expect(c.body).toEqual({ receive_method: "store" });
  });

  it("本文なしは従来どおり（配送。空の JSON を渡す）", async () => {
    fetchMock.mockResolvedValue(upstream(200, { ...prepareOut, receive_method: "delivery", shipping_fee: 550 }));
    const res = await PREPARE(new Request("http://localhost:3000/api/checkout/prepare", { method: "POST", headers: cartHeaders() }));
    expect(res.status).toBe(200);
    expect(callOf(fetchMock).body).toEqual({});
  });

  it("receive_method=pickup は 400 validation_error（FastAPI を呼ばない）。余計な項目は落とす", async () => {
    const bad = await PREPARE(jsonPost("/api/checkout/prepare", { receive_method: "pickup" }, cartHeaders()));
    expect(bad.status).toBe(400);
    expect((await bad.json()).code).toBe("validation_error");
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockResolvedValue(upstream(200, prepareOut));
    await PREPARE(jsonPost("/api/checkout/prepare", { receive_method: "delivery", shipping_fee: 0, member_id: 1 }, cartHeaders()));
    expect(callOf(fetchMock).body).toEqual({ receive_method: "delivery" });
  });

  it("CSRF なしは 403", async () => {
    const res = await PREPARE(jsonPost("/api/checkout/prepare", { receive_method: "store" }, { "Content-Type": "application/json" }));
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

const storeOrder = {
  idempotency_key: IDEM,
  ship_name: "受取 太郎",
  ship_phone: "09012345678",
  guest_email: "pickup@example.com",
  receive_method: "store",
  store_code: "demo-tokyo",
  payment_method: "card",
  display: { subtotal: 3980, shipping_fee: 0, total: 3980 },
};

describe("IT-BFF-022 POST /api/orders（P2-b）", () => {
  it("店舗受け取り: ship_postal_code・ship_address が無くても取り次ぎ、store_code が白リストを通る。sid つきは X-Session-Token が付く", async () => {
    fetchMock.mockResolvedValue(upstream(201, { order_number: "GU-261024-ABCDEFGH", is_member_order: true }));
    const res = await ORDERS(jsonPost("/api/orders", storeOrder, cartHeaders(`sid=${SID_OLD}`)));
    expect(res.status).toBe(201);
    const c = callOf(fetchMock);
    expect(c.url).toBe("http://fastapi.test:8000/api/v1/orders"); // gitleaks:allow（テスト用 URL）
    expect(c.headers.get("X-Session-Token")).toBe(SID_OLD);
    expect(c.headers.get("X-Cart-Token")).toBe(CART_TOKEN);
    expect(c.body).toEqual(storeOrder);
  });

  it("sid なし（ゲスト）は X-Session-Token を付けない", async () => {
    fetchMock.mockResolvedValue(upstream(201, { order_number: "GU-261024-ABCDEFGH" }));
    await ORDERS(jsonPost("/api/orders", storeOrder, cartHeaders()));
    expect(callOf(fetchMock).headers.get("X-Session-Token")).toBeNull();
  });

  it("member_id・status・pickup_code・store_id を足しても落ちる（会員はセッションからだけ決まる）", async () => {
    fetchMock.mockResolvedValue(upstream(201, { order_number: "GU-261024-ABCDEFGH" }));
    await ORDERS(jsonPost("/api/orders", { ...storeOrder, member_id: 7, status: "delivered", pickup_code: "AAAAAAAA", store_id: 1 }, cartHeaders()));
    expect(callOf(fetchMock).body).toEqual(storeOrder);
  });

  it("配送では ship_postal_code・ship_address が必須のまま（無ければ 400 で FastAPI を呼ばない）", async () => {
    const { store_code: _s, ...rest } = storeOrder;
    void _s;
    const res = await ORDERS(jsonPost("/api/orders", { ...rest, receive_method: "delivery" }, cartHeaders()));
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(json.code).toBe("validation_error");
    expect(json.fields.map((f: { name: string }) => f.name).sort()).toEqual(["ship_address", "ship_postal_code"]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("配送の通常の注文はこれまでどおり通る（住所あり・store_code なし）", async () => {
    fetchMock.mockResolvedValue(upstream(201, { order_number: "GU-261024-ABCDEFGH" }));
    const { store_code: _s, ...rest } = storeOrder;
    void _s;
    const delivery = { ...rest, receive_method: "delivery", ship_postal_code: "1000001", ship_address: "東京都　千代田区　千代田1-1", display: { subtotal: 3980, shipping_fee: 550, total: 4530 } };
    const res = await ORDERS(jsonPost("/api/orders", delivery, cartHeaders()));
    expect(res.status).toBe(201);
    expect(callOf(fetchMock).body).toEqual(delivery);
  });

  it("store_code が文字列でない・住所が文字列でない（店舗受け取り）は 400", async () => {
    for (const patch of [{ store_code: 12 }, { ship_postal_code: 1000001 }, { ship_address: ["x"] }]) {
      const res = await ORDERS(jsonPost("/api/orders", { ...storeOrder, ...patch }, cartHeaders()));
      expect(res.status).toBe(400);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("409 invalid_reference（存在しない店舗）は {code, field} のまま透過", async () => {
    fetchMock.mockResolvedValue(upstream(409, { code: "invalid_reference", field: "store_code" }));
    const res = await ORDERS(jsonPost("/api/orders", storeOrder, cartHeaders()));
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ code: "invalid_reference", field: "store_code" });
  });
});
