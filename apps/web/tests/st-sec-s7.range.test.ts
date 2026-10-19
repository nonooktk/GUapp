import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { isValidId, isValidQuantity } from "@/lib/request-validation";

// セキュリティ強化 S7（web 側）: BFF の数量・ID の範囲。quantity は 1〜99 の整数、variant_id・item_id は 1〜2^53-1 の整数。
// 外れたら 400 validation_error（out_of_range）。11〜99 は FastAPI へ渡る（業務上限 10 は FastAPI の 422 limit_exceeded）。
process.env.API_BASE_URL = "http://fastapi.test:8000";
process.env.INTERNAL_TOKEN = "dummy-internal-token"; // gitleaks:allow（テスト用ダミー）
process.env.IMAGE_BASE_URL = "http://localhost:3000";
process.env.APP_ENV = "development";
process.env.SESSION_COOKIE_DOMAIN = "";

const CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret
const headers = { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF, "Content-Type": "application/json" };
const emptyCart = {
  cart_token: null,
  items: [],
  item_count: 0,
  subtotal: 0,
  shipping_fee: 0,
  total: 0,
  free_shipping_threshold: 4990,
  can_checkout: false,
};

let POST: typeof import("@/app/api/cart/items/route").POST;
let PATCH: typeof import("@/app/api/cart/items/[id]/route").PATCH;
let DELETE: typeof import("@/app/api/cart/items/[id]/route").DELETE;
beforeAll(async () => {
  ({ POST } = await import("@/app/api/cart/items/route"));
  ({ PATCH, DELETE } = await import("@/app/api/cart/items/[id]/route"));
});

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  fetchMock.mockReset();
});

const add = (body: unknown) =>
  POST(new Request("http://localhost:3000/api/cart/items", { method: "POST", body: JSON.stringify(body), headers }));
const patch = (id: string, body: unknown) =>
  PATCH(new Request(`http://localhost:3000/api/cart/items/${id}`, { method: "PATCH", body: JSON.stringify(body), headers }), {
    params: Promise.resolve({ id }),
  });

describe("S7 純粋関数", () => {
  it("isValidQuantity: 1〜99 の整数だけ true", () => {
    for (const v of [1, 10, 11, 99]) expect(isValidQuantity(v), String(v)).toBe(true);
    for (const v of [0, 100, -1, 1.5, "1", null, undefined, NaN, Infinity, true]) expect(isValidQuantity(v), String(v)).toBe(false);
  });
  it("isValidId: 1〜2^53-1 の整数だけ true", () => {
    for (const v of [1, 9007199254740991]) expect(isValidId(v), String(v)).toBe(true);
    for (const v of [0, -1, 1.5, 9007199254740992, "1", null, NaN]) expect(isValidId(v), String(v)).toBe(false);
  });
});

describe("S7 POST /api/cart/items の quantity", () => {
  it.each([0, 100, 1.5, "2", -1, null])("quantity=%s は 400 validation_error（out_of_range）。FastAPI を呼ばない", async (quantity) => {
    const res = await add({ variant_id: 1, quantity });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ code: "validation_error", fields: [{ name: "quantity", reason: "out_of_range" }] });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([1, 10, 11, 99])("quantity=%s は FastAPI へ渡る（11 以上の業務上限は FastAPI が 422 limit_exceeded）", async (quantity) => {
    fetchMock.mockResolvedValue(
      quantity > 10
        ? new Response(JSON.stringify({ code: "limit_exceeded", field: "quantity", limit: 10 }), { status: 422 })
        : new Response(JSON.stringify(emptyCart), { status: 201 }),
    );
    const res = await add({ variant_id: 1, quantity });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string)).toEqual({ variant_id: 1, quantity });
    expect(res.status).toBe(quantity > 10 ? 422 : 201);
    if (quantity > 10) expect(await res.json()).toEqual({ code: "limit_exceeded", field: "quantity", limit: 10 });
  });
});

describe("S7 POST /api/cart/items の variant_id", () => {
  it.each([0, -5, 9007199254740992, 1e300])("variant_id=%s は 400（out_of_range）", async (variantId) => {
    const res = await add({ variant_id: variantId, quantity: 1 });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ code: "validation_error", fields: [{ name: "variant_id", reason: "out_of_range" }] });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([1.5, "1", null])("variant_id=%s は 400（format）", async (variantId) => {
    const res = await add({ variant_id: variantId, quantity: 1 });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ code: "validation_error", fields: [{ name: "variant_id", reason: "format" }] });
  });

  it("上限ちょうど（2^53-1）は FastAPI へ渡る", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(emptyCart), { status: 201 }));
    await add({ variant_id: 9007199254740991, quantity: 1 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("S7 PATCH /api/cart/items/[id]", () => {
  it.each([0, 100, 1.5, "3"])("quantity=%s は 400（out_of_range）", async (quantity) => {
    const res = await patch("7", { quantity });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ code: "validation_error", fields: [{ name: "quantity", reason: "out_of_range" }] });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("quantity=11 は FastAPI へ渡る", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ code: "limit_exceeded", field: "quantity", limit: 10 }), { status: 422 }));
    const res = await patch("7", { quantity: 11 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(res.status).toBe(422);
  });

  it("item_id が 0 または 2^53-1 超は 400（out_of_range）、数字でなければ従来どおり 404", async () => {
    for (const id of ["0", "9007199254740992", "99999999999999999999"]) {
      const res = await patch(id, { quantity: 1 });
      expect(res.status, id).toBe(400);
      expect(await res.json()).toEqual({ code: "validation_error", fields: [{ name: "item_id", reason: "out_of_range" }] });
    }
    expect((await patch("abc", { quantity: 1 })).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("DELETE も item_id の範囲を見る。上限ちょうどは FastAPI へ渡る", async () => {
    const del = (id: string) =>
      DELETE(new Request(`http://localhost:3000/api/cart/items/${id}`, { method: "DELETE", headers }), { params: Promise.resolve({ id }) });
    expect((await del("0")).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ code: "not_found" }), { status: 404 }));
    await del("9007199254740991");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
