import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { SearchResponse, SuggestResponse } from "@/lib/types";

// IT-BFF-004: 検索・サジェスト BFF（DS-API-004・004a 取り次ぎ）。設計仕様書 P2 追補a 1 章
// （ブラウザは FastAPI を直接呼ばず「もっと見る」・サジェストは BFF 経由）。
process.env.API_BASE_URL = "http://fastapi.test:8000";
process.env.INTERNAL_TOKEN = "dummy-internal-token"; // gitleaks:allow // pragma: allowlist secret（テスト用ダミー）
process.env.IMAGE_BASE_URL = "http://localhost:3000";
process.env.APP_ENV = "development";
process.env.SESSION_COOKIE_DOMAIN = "";

const searchOut: SearchResponse = {
  query: "シャツ",
  items: [],
  page: 1,
  per_page: 24,
  total: 0,
  has_more: false,
  similar_keywords: [],
  recommended_categories: [],
};

const suggestOut: SuggestResponse = {
  items: [{ id: 1, name: "オーバーサイズシャツ" }],
};

function upstream(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let GET_SEARCH: typeof import("@/app/api/search/route").GET;
let GET_SUGGEST: typeof import("@/app/api/search/suggest/route").GET;

beforeAll(async () => {
  ({ GET: GET_SEARCH } = await import("@/app/api/search/route"));
  ({ GET: GET_SUGGEST } = await import("@/app/api/search/suggest/route"));
});

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe("GET /api/search", () => {
  it("q・page・per_page を FastAPI /api/v1/search へそのまま取り次ぎ、200 の本文をそのまま返す", async () => {
    fetchMock.mockResolvedValue(upstream(200, searchOut));
    const res = await GET_SEARCH(new Request("http://localhost:3000/api/search?q=シャツ&page=2&per_page=24"));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(searchOut);
    expect(res.headers.get("Cache-Control")).toBe("no-store");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://fastapi.test:8000/api/v1/search?q=%E3%82%B7%E3%83%A3%E3%83%84&page=2&per_page=24"); // gitleaks:allow
    const h = new Headers(init.headers);
    expect(h.get("X-Internal-Token")).toBe("dummy-internal-token");
  });

  it("page・per_page が範囲外なら丸める（page は 1〜999、per_page は 1〜24）", async () => {
    fetchMock.mockResolvedValue(upstream(200, searchOut));
    await GET_SEARCH(new Request("http://localhost:3000/api/search?q=a&page=0&per_page=999"));
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("page=1");
    expect(url).toContain("per_page=24");
  });

  it("q が無い・空でも FastAPI にそのまま渡す（400 判定は FastAPI 側に委ねる）", async () => {
    fetchMock.mockResolvedValue(upstream(400, { code: "validation_error", fields: [{ name: "q", reason: "required" }] }));
    const res = await GET_SEARCH(new Request("http://localhost:3000/api/search"));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ code: "validation_error", fields: [{ name: "q", reason: "required" }] });
  });

  it("FastAPI に接続できなければ 503 upstream_unavailable", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const res = await GET_SEARCH(new Request("http://localhost:3000/api/search?q=a"));
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ code: "upstream_unavailable" });
  });
});

describe("GET /api/search/suggest", () => {
  it("q を FastAPI /api/v1/search/suggest へ取り次ぎ、200 の本文をそのまま返す", async () => {
    fetchMock.mockResolvedValue(upstream(200, suggestOut));
    const res = await GET_SUGGEST(new Request("http://localhost:3000/api/search/suggest?q=パ"));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(suggestOut);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://fastapi.test:8000/api/v1/search/suggest?q=%E3%83%91"); // gitleaks:allow
  });

  it("FastAPI の 400 はそのまま透過する", async () => {
    fetchMock.mockResolvedValue(upstream(400, { code: "validation_error", fields: [] }));
    const res = await GET_SUGGEST(new Request("http://localhost:3000/api/search/suggest?q="));
    expect(res.status).toBe(400);
  });

  it("FastAPI に接続できなければ 503 upstream_unavailable", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const res = await GET_SUGGEST(new Request("http://localhost:3000/api/search/suggest?q=a"));
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ code: "upstream_unavailable" });
  });
});
