import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AskAssistantButton from "@/components/chat/AskAssistantButton";
import { chatTree, clearCookies, createChatFetch, json, recommendBody, renderChat, setCsrfCookie, STATUS_OK } from "./helpers/chat";

// テスト設計書 UT-WEB-AI-09: 商品詳細の「この商品について質問する」（設計仕様書 P2 追補d 6.5・REQ-FR-904）。
// 押すとチャットが開き product_id が文脈に入る。パネル上部に「{商品名} について質問中」。×で外れる。送信時に product_id が本文に入り、外した後は入らない。

const nav = vi.hoisted(() => ({ pathname: "/products/12" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));

let chat: ReturnType<typeof createChatFetch>;
beforeEach(() => {
  nav.pathname = "/products/12";
  chat = createChatFetch();
  chat.status(() => json(200, STATUS_OK));
  chat.messages(() => json(200, recommendBody(1)));
  vi.stubGlobal("fetch", chat.mock);
  setCsrfCookie();
});
afterEach(() => {
  vi.unstubAllGlobals();
  clearCookies();
});

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}
const sentBodies = () => chat.calls("messages").map(([, init]) => JSON.parse((init as RequestInit).body as string));
async function send(text: string) {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "送信" }));
  await flush();
}

describe("UT-WEB-AI-09 AskAssistantButton", () => {
  it("押すとチャットが開き、パネル上部に「{商品名} について質問中」。送信すると product_id が本文に入る", async () => {
    renderChat(<AskAssistantButton productId={12} productName="薄手パーカー" />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "この商品について質問する" }));
    await flush();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("薄手パーカー について質問中")).toBeInTheDocument();

    await send("サイズ感を教えて");
    expect(sentBodies()[0]).toEqual({ message: "サイズ感を教えて", product_id: 12 });
  });

  it("×で文脈を外すと表示が消え、以降の送信に product_id が入らない（null）", async () => {
    renderChat(<AskAssistantButton productId={12} productName="薄手パーカー" />);
    fireEvent.click(screen.getByRole("button", { name: "この商品について質問する" }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "質問の対象を外す" }));
    expect(screen.queryByText(/について質問中/)).not.toBeInTheDocument();

    await send("送料は？");
    expect(sentBodies()[0]).toEqual({ message: "送料は？", product_id: null });
  });

  it("別のページへ移ると商品の文脈は外れる（別の商品について聞いてしまわない）", async () => {
    const ui = <AskAssistantButton productId={12} productName="薄手パーカー" />;
    const view = renderChat(ui);
    fireEvent.click(screen.getByRole("button", { name: "この商品について質問する" }));
    await flush();
    expect(screen.getByText("薄手パーカー について質問中")).toBeInTheDocument();

    // 別のページへ移動（パスが変わる。Provider は layout にあるので同じ状態のまま描き直される）
    nav.pathname = "/products/13";
    view.rerender(chatTree(ui));
    expect(screen.queryByText(/について質問中/)).not.toBeInTheDocument();
    await send("送料は？");
    expect(sentBodies()[0]).toEqual({ message: "送料は？", product_id: null });
  });
});
