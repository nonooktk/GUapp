import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ChatLauncher from "@/components/chat/ChatLauncher";
import { CHAT_PANEL_ID, ChatProvider } from "@/components/chat/ChatProvider";
import { createChatFetch, IMAGE_BASE, json, setCsrfCookie, STATUS_OK } from "./helpers/chat";

// テスト設計書 UT-WEB-AI-03: 右下の丸いボタン（設計仕様書 P2 追補d 6.1）。
// aria-label・aria-expanded・aria-controls、56px（44px 以上）、位置のクラス（640px 未満は下 96px、以上は下 24px）、z-40。

beforeEach(() => {
  const chat = createChatFetch();
  chat.status(() => json(200, STATUS_OK));
  vi.stubGlobal("fetch", chat.mock);
  setCsrfCookie();
});
afterEach(() => vi.unstubAllGlobals());

describe("UT-WEB-AI-03 ChatLauncher", () => {
  it("属性: aria-label・aria-expanded（開くと true）・aria-controls がパネルの id", () => {
    render(
      <ChatProvider imageBaseUrl={IMAGE_BASE}>
        <ChatLauncher />
      </ChatProvider>,
    );
    const button = screen.getByRole("button", { name: "AI アシスタントに相談する" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("aria-controls", CHAT_PANEL_ID);
    expect(button).toHaveTextContent("相談");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
  });

  it("大きさと位置: 56px（size-14）、375px 以上 640px 未満は右 16px・下 96px、640px 以上は右 24px・下 24px、z-40", () => {
    render(
      <ChatProvider imageBaseUrl={IMAGE_BASE}>
        <ChatLauncher />
      </ChatProvider>,
    );
    const cls = screen.getByRole("button").className.split(/\s+/);
    for (const c of ["fixed", "size-14", "bottom-24", "right-4", "sm:bottom-6", "sm:right-6", "z-40"]) {
      expect(cls, c).toContain(c);
    }
  });
});
