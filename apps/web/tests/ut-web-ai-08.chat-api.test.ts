import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatApiError, getChatStatus, isSafeInternalHref, parseRetryAfter, resetChat, sendChatMessage } from "@/lib/client/chat-api";
import { clearCookies, CSRF, json, recommendBody, setCsrfCookie, STATUS_OK } from "./helpers/chat";

// テスト設計書 UT-WEB-AI-08: lib/client/chat-api.ts（設計仕様書 P2 追補d 4.1・6.6）。
// POST に X-CSRF-Token と credentials: same-origin。失敗は ChatApiError(status, body, retryAfterSec)。Retry-After が数字でなければ null。壊れた JSON でも ChatApiError。

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  clearCookies();
});

async function caught(promise: Promise<unknown>): Promise<ChatApiError> {
  try {
    await promise;
  } catch (e) {
    expect(e).toBeInstanceOf(ChatApiError);
    return e as ChatApiError;
  }
  throw new Error("失敗するはず");
}

describe("UT-WEB-AI-08 chat-api", () => {
  it("sendChatMessage: POST /api/chat/messages に X-CSRF-Token・credentials same-origin・本文（message と product_id）", async () => {
    setCsrfCookie();
    fetchMock.mockResolvedValue(json(200, recommendBody(2)));
    const res = await sendChatMessage({ message: "黒のパーカー", productId: 12 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/chat/messages");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    const h = new Headers(init.headers);
    expect(h.get("X-CSRF-Token")).toBe(CSRF);
    expect(h.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ message: "黒のパーカー", product_id: 12 });

    expect(res.turns_used).toBe(2);
    expect(res.turns_limit).toBe(10);
    expect(res.notice).toBeNull();
    expect(res.reply.products[0]).toMatchObject({ id: 12, price_incl_tax: 2990, sold_out: false });
    expect(res.reply.guide).toEqual([]); // null は空配列に整える
  });

  it("csrf_token が未発行なら先に GET /api/chat/status で発行させる（カートは作らない）", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/chat/status") {
        document.cookie = `csrf_token=${CSRF}; path=/`;
        return json(200, STATUS_OK);
      }
      return json(200, recommendBody(1));
    });
    await sendChatMessage({ message: "こんにちは", productId: null });
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/chat/status", "/api/chat/messages"]);
    expect((fetchMock.mock.calls[0] as [string, RequestInit])[1].method).toBe("GET");
  });

  it("csrf_token が発行されなければ 403 の ChatApiError（送信しない）", async () => {
    fetchMock.mockResolvedValue(json(200, STATUS_OK));
    const err = await caught(sendChatMessage({ message: "x", productId: null }));
    expect(err.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("getChatStatus: 値を整える。resetChat: POST /api/chat/reset に CSRF", async () => {
    setCsrfCookie();
    fetchMock.mockResolvedValueOnce(json(200, { ...STATUS_OK, provider: "stub", extra: "x" }));
    expect(await getChatStatus()).toEqual({ ...STATUS_OK, provider: "stub" });
    expect((fetchMock.mock.calls[0] as [string, RequestInit])[1].method).toBe("GET");

    fetchMock.mockResolvedValueOnce(json(200, { ok: true }));
    await resetChat();
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/chat/reset");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe(CSRF);
    expect(init.credentials).toBe("same-origin");
  });

  it("失敗は ChatApiError(status, body, retryAfterSec)。Retry-After が数字でなければ null", async () => {
    setCsrfCookie();
    fetchMock.mockResolvedValueOnce(json(429, { code: "rate_limited" }, { "Retry-After": "30" }));
    const e1 = await caught(sendChatMessage({ message: "x", productId: null }));
    expect([e1.status, e1.body?.code, e1.retryAfterSec]).toEqual([429, "rate_limited", 30]);

    fetchMock.mockResolvedValueOnce(json(429, { code: "rate_limited" }, { "Retry-After": "abc" }));
    expect((await caught(sendChatMessage({ message: "x", productId: null }))).retryAfterSec).toBeNull();

    fetchMock.mockResolvedValueOnce(json(429, { code: "rate_limited" }, { "Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT" }));
    expect((await caught(sendChatMessage({ message: "x", productId: null }))).retryAfterSec).toBeNull();

    fetchMock.mockResolvedValueOnce(json(409, { code: "turn_limit", limit: 10 }));
    const e4 = await caught(sendChatMessage({ message: "x", productId: null }));
    expect([e4.status, e4.body]).toEqual([409, { code: "turn_limit", limit: 10 }]);
  });

  it("本文が壊れた JSON のときも ChatApiError（失敗は body null、成功は bad_response）。通信失敗は status 0", async () => {
    setCsrfCookie();
    fetchMock.mockResolvedValueOnce(new Response("<html>oops</html>", { status: 502 }));
    const e1 = await caught(sendChatMessage({ message: "x", productId: null }));
    expect([e1.status, e1.body]).toEqual([502, null]);

    fetchMock.mockResolvedValueOnce(new Response("not json", { status: 200 }));
    const e2 = await caught(sendChatMessage({ message: "x", productId: null }));
    expect(e2.body?.code).toBe("bad_response");

    fetchMock.mockResolvedValueOnce(json(200, { reply: "文字列" }));
    expect((await caught(sendChatMessage({ message: "x", productId: null }))).body?.code).toBe("bad_response");

    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const e4 = await caught(sendChatMessage({ message: "x", productId: null }));
    expect([e4.status, e4.body]).toEqual([0, null]);
  });

  it("応答の整形: 出典の title は label に、サイト外のリンク・不正な商品は捨てる", async () => {
    setCsrfCookie();
    fetchMock.mockResolvedValue(
      json(200, {
        reply: {
          intent: "faq",
          message: "ご案内します",
          products: [{ id: "x", name: "bad" }, { id: 5, name: "ok", price_incl_tax: 990, image_path: null, sold_out: true, reason: "r" }],
          sources: [{ title: "よくある質問", href: "/contents/faq" }, { title: "外部", href: "https://evil.example" }, { title: "相対", href: "//evil.example" }],
          guide: { links: [{ label: "企業情報", href: "/contents/company" }, { label: "js", href: "javascript:alert(1)" }] },
        },
        turns_used: 1,
        turns_limit: 10,
        notice: "masked",
      }),
    );
    const res = await sendChatMessage({ message: "x", productId: null });
    expect(res.reply.products).toHaveLength(1);
    expect(res.reply.products[0]).toMatchObject({ id: 5, sold_out: true, image_path: null });
    expect(res.reply.sources).toEqual([{ label: "よくある質問", href: "/contents/faq" }]);
    expect(res.reply.guide).toEqual([{ label: "企業情報", href: "/contents/company" }]);
    expect(res.notice).toBe("masked");
  });

  it("product_info（文脈の商品への回答）は intent を保ち、出典の商品ページのリンクを残す", async () => {
    setCsrfCookie();
    fetchMock.mockResolvedValue(
      json(200, {
        reply: {
          intent: "product_info",
          message: "素材は綿100%です。",
          products: [],
          sources: [{ title: "商品ページ", href: "/products/12" }],
          guide: null,
        },
        turns_used: 1,
        turns_limit: 10,
        notice: null,
      }),
    );
    const res = await sendChatMessage({ message: "この商品の素材を教えて", productId: 12 });
    expect(res.reply.intent).toBe("product_info");
    expect(res.reply.sources).toEqual([{ label: "商品ページ", href: "/products/12" }]);
    expect(res.reply.products).toEqual([]);
  });

  it("parseRetryAfter・isSafeInternalHref の境界", () => {
    expect(parseRetryAfter("1")).toBe(1);
    expect(parseRetryAfter("0")).toBeNull();
    expect(parseRetryAfter("-5")).toBeNull();
    expect(parseRetryAfter("1.5")).toBeNull();
    expect(parseRetryAfter(null)).toBeNull();
    expect(isSafeInternalHref("/contents/faq")).toBe(true);
    expect(isSafeInternalHref("/products/12")).toBe(true);
    for (const bad of ["https://evil.example", "//evil.example", "javascript:alert(1)", "contents/faq", "/a b", "/<x>", 5, null]) {
      expect(isSafeInternalHref(bad)).toBe(false);
    }
  });
});
