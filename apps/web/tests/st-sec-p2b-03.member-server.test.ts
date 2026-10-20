import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { callOf, SID_NEW, upstream } from "./helpers/bff";

// ST-SEC-56（未ログインの /mypage は /login?next=/mypage へ）・ST-SEC-45（失効した sid は 401 → /login）・ST-SEC-47（他人・ゲストの注文は 404）の
// Web 側（lib/server/member.ts）。設計仕様書 4.7・6.4・6.5・DS-DEC-86

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
beforeEach(() => {
  cookieJar = {};
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  fetchMock.mockReset();
});

async function member() {
  return import("@/lib/server/member");
}

describe("lib/server/member.ts", () => {
  it("sid が無い: FastAPI を呼ばずに /login?next=/mypage へ redirect", async () => {
    const m = await member();
    await expect(m.loadMe()).rejects.toMatchObject({ to: "/login?next=/mypage" });
    await expect(m.loadMyOrders(1)).rejects.toMatchObject({ to: "/login?next=/mypage" });
    await expect(m.loadMyOrder("GU-261024-ABCDEFGH")).rejects.toMatchObject({ to: "/login?next=/mypage" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("形が違う sid（43 文字でない）も未ログイン扱い", async () => {
    cookieJar = { sid: "short" };
    const m = await member();
    await expect(m.loadMe()).rejects.toBeInstanceOf(RedirectSignal);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sid あり: X-Session-Token・X-Internal-Token を付けて /me を呼び、200 の本文を返す", async () => {
    cookieJar = { sid: SID_NEW };
    fetchMock.mockResolvedValue(upstream(200, { name: "デモ 一郎", email: "demo-member1@example.com", email_verified: true, personalize_opt_in: false }));
    const m = await member();
    const r = await m.loadMe();
    expect(r).toEqual({ kind: "ok", data: expect.objectContaining({ name: "デモ 一郎" }) });
    const c = callOf(fetchMock);
    expect(c.url).toBe("http://fastapi.test:8000/api/v1/me"); // gitleaks:allow（テスト用 URL）
    expect(c.headers.get("X-Session-Token")).toBe(SID_NEW);
    expect(c.headers.get("X-Internal-Token")).toBe("dummy-internal-token");
  });

  it("401（失効・不明・匿名化済み）は /login?next=/mypage へ redirect", async () => {
    cookieJar = { sid: SID_NEW };
    fetchMock.mockResolvedValue(upstream(401, { code: "unauthorized" }));
    const m = await member();
    await expect(m.loadMyOrders(1)).rejects.toMatchObject({ to: "/login?next=/mypage" });
  });

  it("404 は not_found（他人の注文・ゲスト注文・不存在を区別しない）。注文番号は URL エンコードして渡す", async () => {
    cookieJar = { sid: SID_NEW };
    fetchMock.mockResolvedValue(upstream(404, { code: "not_found" }));
    const m = await member();
    expect(await m.loadMyOrder("GU-261024-ABCDEFGH")).toEqual({ kind: "not_found" });
    expect(callOf(fetchMock).url).toBe("http://fastapi.test:8000/api/v1/me/orders/GU-261024-ABCDEFGH"); // gitleaks:allow（テスト用 URL）
  });

  it("接続不可・500 は error（redirect しない）", async () => {
    cookieJar = { sid: SID_NEW };
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const m = await member();
    expect(await m.loadMe()).toEqual({ kind: "error" });
    fetchMock.mockResolvedValueOnce(upstream(500, { code: "internal_error" }));
    expect(await m.loadMe()).toEqual({ kind: "error" });
  });

  it("一覧は page・per_page をクエリに載せる", async () => {
    cookieJar = { sid: SID_NEW };
    fetchMock.mockResolvedValue(upstream(200, { items: [], page: 2, per_page: 10, total: 0, has_more: false }));
    const m = await member();
    await m.loadMyOrders(2);
    expect(callOf(fetchMock).url).toBe("http://fastapi.test:8000/api/v1/me/orders?page=2&per_page=10"); // gitleaks:allow（テスト用 URL）
  });

  it("getMemberOrNull: sid なし・401・接続不可は null（redirect しない）。有効なら会員情報", async () => {
    const m = await member();
    expect(await m.getMemberOrNull()).toBeNull();
    cookieJar = { sid: SID_NEW };
    fetchMock.mockResolvedValueOnce(upstream(401, { code: "unauthorized" }));
    expect(await m.getMemberOrNull()).toBeNull();
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    expect(await m.getMemberOrNull()).toBeNull();
    fetchMock.mockResolvedValueOnce(upstream(200, { name: "n", email: "a@example.com", email_verified: true, personalize_opt_in: false }));
    expect(await m.getMemberOrNull()).toMatchObject({ name: "n" });
  });

  it("hasSessionCookie: sid の有無だけを見る（FastAPI を呼ばない）", async () => {
    const m = await member();
    expect(await m.hasSessionCookie()).toBe(false);
    cookieJar = { sid: "anything" };
    expect(await m.hasSessionCookie()).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
