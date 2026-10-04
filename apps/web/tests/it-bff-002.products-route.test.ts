import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProductListResponse } from "@/lib/types";

// IT-BFF-002: 商品一覧 BFF（DS-API-002 取り次ぎ）。一覧の「もっと見る」がクライアントから呼ぶ。
// kind（種類。ALL で性別をまたいで絞る）を gender・category と同じ検査で FastAPI へ取り次ぐ。
process.env.API_BASE_URL = "http://fastapi.test:8000";
process.env.INTERNAL_TOKEN = "dummy-internal-token"; // gitleaks:allow // pragma: allowlist secret（テスト用ダミー）
process.env.IMAGE_BASE_URL = "http://localhost:3000";
process.env.APP_ENV = "development";
process.env.SESSION_COOKIE_DOMAIN = "";

const listOut: ProductListResponse = { items: [], page: 2, per_page: 24, total: 0, has_more: false };

function upstream(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let GET: typeof import("@/app/api/products/route").GET;
let buildProductsQuery: typeof import("@/lib/server/catalog").buildProductsQuery;

beforeAll(async () => {
  ({ GET } = await import("@/app/api/products/route"));
  ({ buildProductsQuery } = await import("@/lib/server/catalog"));
});

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

function upstreamUrl(): URL {
  const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
  return new URL(url);
}

describe("buildProductsQuery", () => {
  it("kind を付ける。空・未指定なら付けない", () => {
    expect(buildProductsQuery({ kind: "tops", page: 2 })).toBe("kind=tops&page=2&per_page=24");
    expect(buildProductsQuery({ kind: "", page: 1 })).toBe("page=1&per_page=24");
    expect(buildProductsQuery({ page: 1 })).toBe("page=1&per_page=24");
  });

  it("gender・category・kind をそろえて渡せる（順は gender → category → kind → page → per_page）", () => {
    expect(buildProductsQuery({ gender: "women", category: "women-tops", kind: "tops" })).toBe(
      "gender=women&category=women-tops&kind=tops&page=1&per_page=24",
    );
  });
});

describe("GET /api/products", () => {
  it("kind を FastAPI /api/v1/products へ取り次ぐ（gender・category は付けない）", async () => {
    fetchMock.mockResolvedValue(upstream(200, listOut));
    const res = await GET(new Request("http://localhost:3000/api/products?kind=tops&page=2&per_page=24"));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(listOut);
    expect(res.headers.get("Cache-Control")).toBe("no-store");

    const u = upstreamUrl();
    expect(u.origin + u.pathname).toBe("http://fastapi.test:8000/api/v1/products");
    expect(u.searchParams.get("kind")).toBe("tops");
    expect(u.searchParams.get("page")).toBe("2");
    expect(u.searchParams.has("gender")).toBe(false);
    expect(u.searchParams.has("category")).toBe(false);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("X-Internal-Token")).toBe("dummy-internal-token");
  });

  it("gender・category と併用しても 3 つとも取り次ぐ", async () => {
    fetchMock.mockResolvedValue(upstream(200, listOut));
    await GET(new Request("http://localhost:3000/api/products?gender=men&category=men-tops&kind=tops"));
    const u = upstreamUrl();
    expect(u.searchParams.get("gender")).toBe("men");
    expect(u.searchParams.get("category")).toBe("men-tops");
    expect(u.searchParams.get("kind")).toBe("tops");
  });

  it("kind が無い・空・形が不正（大文字・記号）なら FastAPI へは渡さない", async () => {
    for (const q of ["", "?kind=", "?kind=TOPS", "?kind=to%20ps", "?kind=tops%3Bdrop", `?kind=${"a".repeat(65)}`]) {
      fetchMock.mockReset();
      fetchMock.mockResolvedValue(upstream(200, listOut));
      await GET(new Request(`http://localhost:3000/api/products${q}`));
      expect(upstreamUrl().searchParams.has("kind"), q).toBe(false);
    }
  });

  it("FastAPI の 400 はそのまま透過する", async () => {
    const body = { code: "validation_error", fields: [{ name: "kind", reason: "format" }] };
    fetchMock.mockResolvedValue(upstream(400, body));
    const res = await GET(new Request("http://localhost:3000/api/products?kind=" + "a".repeat(33)));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual(body);
  });

  it("FastAPI に接続できなければ 503 upstream_unavailable", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const res = await GET(new Request("http://localhost:3000/api/products?kind=tops"));
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ code: "upstream_unavailable" });
  });
});
