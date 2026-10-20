import { render } from "@testing-library/react";
import { vi } from "vitest";
import ChatLauncher from "@/components/chat/ChatLauncher";
import ChatPanel from "@/components/chat/ChatPanel";
import { ChatProvider } from "@/components/chat/ChatProvider";
import type { ReactNode } from "react";

/** AI アシスタントの画面テスト共通の道具（fetch のモックと描画） */

export const CSRF = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde"; // gitleaks:allow // pragma: allowlist secret
export const IMAGE_BASE = "http://img.test";

export const STATUS_OK = { available: true, reason: null, provider: "openai", turns_limit: 10, message_max_chars: 300 };

export const PRODUCT = {
  id: 12,
  name: "薄手パーカー",
  price_incl_tax: 2990,
  image_path: "/products/012/1.png",
  sold_out: false,
  reason: "薄手で重ね着しやすいためです。",
};

export function recommendBody(turnsUsed = 1, extra: Record<string, unknown> = {}) {
  return {
    reply: {
      intent: "recommend",
      message: "春先に羽織れる軽めの商品を選びました。",
      products: [PRODUCT],
      sources: [],
      guide: null,
    },
    turns_used: turnsUsed,
    turns_limit: 10,
    notice: null,
    ...extra,
  };
}

export function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

type Responder = () => Response | Promise<Response>;

/**
 * `/api/chat/*` 向けの fetch モック。パスごとに応答を順に積む（積んだ分を使い切ったら最後の応答を繰り返す）。
 * 応答は関数で渡すと呼ばれるたびに作る（Response は 1 回しか読めないため）。
 */
export function createChatFetch() {
  const queues: Record<string, Responder[]> = { status: [], messages: [], reset: [] };
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void init;
    const url = String(input);
    const key = url.includes("/api/chat/status") ? "status" : url.includes("/api/chat/messages") ? "messages" : url.includes("/api/chat/reset") ? "reset" : "";
    const queue = queues[key];
    if (!queue || queue.length === 0) throw new Error(`unexpected fetch ${url}`);
    const next = queue.length > 1 ? queue.shift()! : queue[0];
    return next();
  });
  return {
    mock,
    status: (...r: Responder[]) => void queues.status.push(...r),
    messages: (...r: Responder[]) => void queues.messages.push(...r),
    reset: (...r: Responder[]) => void queues.reset.push(...r),
    calls: (key: "status" | "messages" | "reset") =>
      mock.mock.calls.filter(([u]) => String(u).includes(`/api/chat/${key}`)) as unknown as [string, RequestInit][],
  };
}

export function setCsrfCookie() {
  document.cookie = `csrf_token=${CSRF}; path=/`;
}

export function clearCookies() {
  for (const part of document.cookie.split(";")) {
    const name = part.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; Max-Age=0; path=/`;
  }
}

export function chatTree(extra?: ReactNode) {
  return (
    <ChatProvider imageBaseUrl={IMAGE_BASE}>
      <ChatLauncher />
      <ChatPanel />
      {extra}
    </ChatProvider>
  );
}

export function renderChat(extra?: ReactNode) {
  return render(chatTree(extra));
}
