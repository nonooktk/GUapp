import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { callOf, CSRF, csrfHeaders, jsonPost, SID_OLD, upstream } from "./helpers/bff";

// テスト設計書 IT-BFF-007（POST /api/restock-notifications）。設計仕様書 4.5・DS-API-007・DS-DEC-80。

let POST: (request: Request) => Promise<Response>;
beforeAll(async () => {
  ({ POST } = await import("@/app/api/restock-notifications/route"));
});

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

const body = { variant_id: 4521, email: "demo@example.com" };

describe("IT-BFF-007 再入荷の申込 BFF", () => {
  it("有効な sid つき: X-Session-Token が付き、variant_id・email だけが FastAPI に渡る（member_id・notified_at は落ちる）", async () => {
    fetchMock.mockResolvedValue(upstream(200, { status: "registered" }));
    const res = await POST(jsonPost("/api/restock-notifications", { ...body, member_id: 9, notified_at: "2026-01-01T00:00:00Z" }, csrfHeaders(`sid=${SID_OLD}`)));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: "registered" });
    const c = callOf(fetchMock);
    expect(c.url).toBe("http://fastapi.test:8000/api/v1/restock-notifications"); // gitleaks:allow（テスト用 URL）
    expect(c.headers.get("X-Session-Token")).toBe(SID_OLD);
    expect(c.headers.get("X-Internal-Token")).toBe("dummy-internal-token");
    expect(c.headers.get("X-Forwarded-For")).toBe("127.0.0.1");
    expect(c.body).toEqual(body);
  });

  it("sid なし（ゲスト）: X-Session-Token は付かない", async () => {
    fetchMock.mockResolvedValue(upstream(200, { status: "registered" }));
    await POST(jsonPost("/api/restock-notifications", body, csrfHeaders()));
    expect(callOf(fetchMock).headers.get("X-Session-Token")).toBeNull();
  });

  it("variant_id は整数（1〜2^53-1）だけ通す。文字列・小数・0・範囲外・欠落は 400 で FastAPI を呼ばない", async () => {
    for (const bad of ["4521", 1.5, 0, -1, Number.MAX_SAFE_INTEGER + 2, null, undefined]) {
      const res = await POST(jsonPost("/api/restock-notifications", { variant_id: bad, email: "demo@example.com" }, csrfHeaders()));
      expect(res.status, String(bad)).toBe(400);
      expect((await res.json()).code).toBe("validation_error");
    }
    const noEmail = await POST(jsonPost("/api/restock-notifications", { variant_id: 1 }, csrfHeaders()));
    expect(noEmail.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("CSRF なし・不一致・Origin 不一致は 403（FastAPI を呼ばない）", async () => {
    const noToken = await POST(jsonPost("/api/restock-notifications", body, { cookie: `csrf_token=${CSRF}`, "Content-Type": "application/json" }));
    expect(noToken.status).toBe(403);
    const evil = await POST(jsonPost("/api/restock-notifications", body, csrfHeaders("", { origin: "https://evil.example" })));
    expect(evil.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("409 in_stock・404・422 limit_exceeded（field・limit）・422 unsupported_value・429 は {code,...} のまま透過", async () => {
    const cases: [number, Record<string, unknown>][] = [
      [409, { code: "in_stock" }],
      [404, { code: "not_found" }],
      [422, { code: "limit_exceeded", field: "email", limit: 10 }],
      [422, { code: "unsupported_value", field: "email" }],
      [429, { code: "rate_limited" }],
    ];
    for (const [status, b] of cases) {
      fetchMock.mockResolvedValueOnce(upstream(status, b));
      const res = await POST(jsonPost("/api/restock-notifications", body, csrfHeaders()));
      expect(res.status).toBe(status);
      expect(await res.json()).toEqual(b);
    }
  });
});
