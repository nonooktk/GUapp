import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { callOf, SID_NEW, upstream } from "./helpers/bff";
import { ASID_NEW } from "./helpers/admin";

// テスト設計書 UT-WEB-51（管理データの読み込み lib/server/admin.ts）・ST-SEC-80 / ST-SEC-93 の Web 側。設計仕様書 P2 追補c 4.5・6.2

class RedirectSignal extends Error {
  constructor(readonly to: string) {
    super(`redirect:${to}`);
  }
}
let cookieJar: Record<string, string> = {};
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (name in cookieJar ? { name, value: cookieJar[name] } : undefined),
    has: (name: string) => name in cookieJar,
  }),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new RedirectSignal(to);
  },
}));

const fetchMock = vi.fn();
let errors: string[];
beforeEach(() => {
  cookieJar = {};
  errors = [];
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(console, "error").mockImplementation((...a: unknown[]) => void errors.push(JSON.stringify(a)));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  fetchMock.mockReset();
});

async function admin() {
  return import("@/lib/server/admin");
}

describe("UT-WEB-51 管理データの読み込み", () => {
  it("asid が無い: FastAPI を呼ばずに /admin/login へ redirect(どの読み込みでも)", async () => {
    const m = await admin();
    await expect(m.loadAdminProducts("page=1")).rejects.toMatchObject({ to: "/admin/login" });
    await expect(m.loadAdminProduct("1")).rejects.toMatchObject({ to: "/admin/login" });
    await expect(m.loadAdminOrders("page=1")).rejects.toMatchObject({ to: "/admin/login" });
    await expect(m.loadAdminOrder("GU-261024-ABCDEFGH")).rejects.toMatchObject({ to: "/admin/login" });
    await expect(m.loadAdminSettings()).rejects.toMatchObject({ to: "/admin/login" });
    await expect(m.requireAdmin()).rejects.toMatchObject({ to: "/admin/login" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("形が違う asid(43 文字でない)も未ログイン扱い。会員の sid だけがあっても管理者としては扱わない(ST-SEC-93)", async () => {
    const m = await admin();
    cookieJar = { asid: "short" };
    await expect(m.loadAdminProducts("page=1")).rejects.toBeInstanceOf(RedirectSignal);
    cookieJar = { sid: SID_NEW };
    await expect(m.loadAdminProducts("page=1")).rejects.toBeInstanceOf(RedirectSignal);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("asid あり: X-Admin-Session-Token・X-Internal-Token を付けて呼び、200 の本文を返す。会員の sid は渡さない", async () => {
    cookieJar = { asid: ASID_NEW, sid: SID_NEW };
    fetchMock.mockResolvedValue(upstream(200, { items: [], page: 1, per_page: 20, total: 0, has_more: false }));
    const m = await admin();
    const r = await m.loadAdminProducts("q=T&page=2");
    expect(r).toEqual({ kind: "ok", data: expect.objectContaining({ total: 0 }) });
    const c = callOf(fetchMock);
    expect(c.url).toBe("http://fastapi.test:8000/api/v1/admin/products?q=T&page=2"); // gitleaks:allow（テスト用 URL）
    expect(c.headers.get("X-Admin-Session-Token")).toBe(ASID_NEW);
    expect(c.headers.get("X-Internal-Token")).toBe("dummy-internal-token");
    expect(c.headers.get("X-Session-Token")).toBeNull();
  });

  it("401・403(会員のセッションの持ち込みを含む)は /admin/login へ redirect", async () => {
    cookieJar = { asid: ASID_NEW };
    const m = await admin();
    fetchMock.mockResolvedValueOnce(upstream(401, { code: "unauthorized" }));
    await expect(m.loadAdminOrders("page=1")).rejects.toMatchObject({ to: "/admin/login" });
    fetchMock.mockResolvedValueOnce(upstream(403, { code: "forbidden" }));
    await expect(m.loadAdminSettings()).rejects.toMatchObject({ to: "/admin/login" });
  });

  it("404 は not_found(ページが notFound() にする)。注文番号・商品 ID は URL エンコードして渡す", async () => {
    cookieJar = { asid: ASID_NEW };
    fetchMock.mockImplementation(async () => upstream(404, { code: "not_found" }));
    const m = await admin();
    expect(await m.loadAdminOrder("GU-261024-ABCDEFGH")).toEqual({ kind: "not_found" });
    expect(callOf(fetchMock).url).toBe("http://fastapi.test:8000/api/v1/admin/orders/GU-261024-ABCDEFGH"); // gitleaks:allow（テスト用 URL）
    await m.loadAdminOrder("../../me");
    expect(callOf(fetchMock, 1).url).toBe("http://fastapi.test:8000/api/v1/admin/orders/..%2F..%2Fme"); // gitleaks:allow（テスト用 URL）
  });

  it("500・接続不可は error(redirect しない。LoadError を出すのはページ側)。400・422 は status と body を返す", async () => {
    cookieJar = { asid: ASID_NEW };
    const m = await admin();
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    expect(await m.loadAdminSettings()).toEqual({ kind: "error", status: 503, body: { code: "upstream_unavailable" } });
    fetchMock.mockResolvedValueOnce(upstream(500, { code: "internal_error" }));
    expect(await m.loadAdminSettings()).toMatchObject({ kind: "error", status: 500 });
    fetchMock.mockResolvedValueOnce(upstream(422, { code: "limit_exceeded", field: "to", limit: 366 }));
    expect(await m.loadAdminOrders("from=2020-01-01&to=2026-01-01&page=1")).toEqual({
      kind: "error",
      status: 422,
      body: { code: "limit_exceeded", field: "to", limit: 366 },
    });
  });

  it("ログに検索語(メール)・注文番号・トークンを書かない", async () => {
    cookieJar = { asid: ASID_NEW };
    const m = await admin();
    fetchMock.mockResolvedValueOnce(upstream(500, { code: "internal_error" }));
    await m.loadAdminOrders("email=private-person%40example.com&page=1");
    fetchMock.mockResolvedValueOnce(upstream(500, { code: "internal_error" }));
    await m.loadAdminOrder("GU-261024-ABCDEFGH");
    const all = errors.join("\n");
    expect(all).toContain("/admin/orders");
    expect(all).not.toContain("private-person");
    expect(all).not.toContain("GU-261024-ABCDEFGH");
    expect(all).not.toContain(ASID_NEW);
  });

  it("getAdminOrNull: 管理者なら情報、asid なし・401・403・接続不可は null(redirect しない)", async () => {
    const m = await admin();
    expect(await m.getAdminOrNull()).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    cookieJar = { asid: ASID_NEW };
    fetchMock.mockResolvedValueOnce(upstream(200, { login_id: "demo-staff", role: "staff" }));
    expect(await m.getAdminOrNull()).toEqual({ login_id: "demo-staff", role: "staff" });
    expect(callOf(fetchMock).url).toBe("http://fastapi.test:8000/api/v1/admin/me"); // gitleaks:allow（テスト用 URL）
    fetchMock.mockResolvedValueOnce(upstream(401, { code: "unauthorized" }));
    expect(await m.getAdminOrNull()).toBeNull();
    fetchMock.mockResolvedValueOnce(upstream(403, { code: "forbidden" }));
    expect(await m.getAdminOrNull()).toBeNull();
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    expect(await m.getAdminOrNull()).toBeNull();
  });
});
