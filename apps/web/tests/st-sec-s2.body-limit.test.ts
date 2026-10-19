import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

// セキュリティ強化 S2: BFF の本文は 8192 バイトまで。超えたら 413 `{"code":"payload_too_large"}`、FastAPI は呼ばない。
process.env.API_BASE_URL = "http://fastapi.test:8000";
process.env.INTERNAL_TOKEN = "dummy-internal-token"; // gitleaks:allow（テスト用ダミー）
process.env.IMAGE_BASE_URL = "http://localhost:3000";
process.env.APP_ENV = "development";
process.env.SESSION_COOKIE_DOMAIN = "";

const CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret
const headers = { cookie: `csrf_token=${CSRF}`, "X-CSRF-Token": CSRF, "Content-Type": "application/json" };

/** JSON として正しい本文を、ちょうど `bytes` バイトにする */
function jsonOfBytes(bytes: number): string {
  const base = JSON.stringify({ variant_id: 1, quantity: 1, pad: "" });
  return JSON.stringify({ variant_id: 1, quantity: 1, pad: "a".repeat(bytes - base.length) });
}

let readJsonBody: typeof import("@/lib/server/cart-proxy").readJsonBody;
let POST: typeof import("@/app/api/cart/items/route").POST;
let PATCH: typeof import("@/app/api/cart/items/[id]/route").PATCH;
let ORDERS_POST: typeof import("@/app/api/orders/route").POST;
let LOOKUP_POST: typeof import("@/app/api/orders/[orderNumber]/lookup/route").POST;

beforeAll(async () => {
  ({ readJsonBody } = await import("@/lib/server/cart-proxy"));
  ({ POST } = await import("@/app/api/cart/items/route"));
  ({ PATCH } = await import("@/app/api/cart/items/[id]/route"));
  ({ POST: ORDERS_POST } = await import("@/app/api/orders/route"));
  ({ POST: LOOKUP_POST } = await import("@/app/api/orders/[orderNumber]/lookup/route"));
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

describe("S2 readJsonBody", () => {
  const post = (body: string, extra: Record<string, string> = {}) =>
    new Request("http://localhost:3000/api/cart/items", { method: "POST", body, headers: extra });

  it("8192 バイトちょうどは読める", async () => {
    const text = jsonOfBytes(8192);
    expect(new TextEncoder().encode(text).length).toBe(8192);
    const result = await readJsonBody(post(text));
    expect(result.ok).toBe(true);
  });

  it("8193 バイトは 413 payload_too_large", async () => {
    const text = jsonOfBytes(8193);
    const result = await readJsonBody(post(text));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.response.status).toBe(413);
      expect(await result.response.json()).toEqual({ code: "payload_too_large" });
    }
  });

  it("Content-Length が 8192 を超えていれば本文を読まずに 413", async () => {
    const result = await readJsonBody(post("{}", { "Content-Length": "9000" }));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.response.status).toBe(413);
  });

  it("Content-Length が無い（チャンク転送）でも、読み取った量が 8192 を超えたら 413", async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const chunk = new TextEncoder().encode("a".repeat(4096));
        controller.enqueue(chunk);
        controller.enqueue(chunk);
        controller.enqueue(chunk);
        controller.close();
      },
    });
    const request = new Request("http://localhost:3000/api/cart/items", {
      method: "POST",
      body: stream,
      duplex: "half",
    } as RequestInit);
    const result = await readJsonBody(request);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.response.status).toBe(413);
  });

  it("壊れた JSON・オブジェクト以外・空の本文は body: null（413 ではない）", async () => {
    for (const text of ["{", "[1]", "123", ""]) {
      const result = await readJsonBody(post(text));
      expect(result).toEqual({ ok: true, body: null });
    }
  });
});

describe("S2 各 BFF は 413 を返し、FastAPI を呼ばない", () => {
  const big = jsonOfBytes(8193);

  it("POST /api/cart/items", async () => {
    const res = await POST(new Request("http://localhost:3000/api/cart/items", { method: "POST", body: big, headers }));
    expect(res.status).toBe(413);
    expect(await res.json()).toEqual({ code: "payload_too_large" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("PATCH /api/cart/items/[id]", async () => {
    const res = await PATCH(
      new Request("http://localhost:3000/api/cart/items/7", { method: "PATCH", body: big, headers }),
      { params: Promise.resolve({ id: "7" }) },
    );
    expect(res.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("POST /api/orders", async () => {
    const res = await ORDERS_POST(new Request("http://localhost:3000/api/orders", { method: "POST", body: big, headers }));
    expect(res.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("POST /api/orders/[n]/lookup", async () => {
    const res = await LOOKUP_POST(
      new Request("http://localhost:3000/api/orders/GU-261019-ABCD2345/lookup", { method: "POST", body: big, headers }),
      { params: Promise.resolve({ orderNumber: "GU-261019-ABCD2345" }) },
    );
    expect(res.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
