import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCookies, createChatFetch, json, recommendBody, renderChat, setCsrfCookie, STATUS_OK } from "./helpers/chat";

// テスト設計書 UT-WEB-AI-04: パネルのダイアログ（設計仕様書 P2 追補d 6.4）。
// 開く→Tab を繰り返す→Escape→閉じる。role・aria・初期フォーカス・循環・フォーカスの復帰・role="log"・aria-busy。

let chat: ReturnType<typeof createChatFetch>;
beforeEach(() => {
  chat = createChatFetch();
  chat.status(() => json(200, { ...STATUS_OK, provider: "stub" }));
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
const launcher = () => screen.getByRole("button", { name: "AI アシスタントに相談する" });

async function openPanel() {
  renderChat();
  launcher().focus();
  fireEvent.click(launcher());
  await flush();
}

describe("UT-WEB-AI-04 ChatPanel のダイアログ", () => {
  it("role=dialog・aria-modal・aria-labelledby（見出し）。stub のときだけ見出しに（デモ応答）", async () => {
    await openPanel();
    const dialog = screen.getByRole("dialog", { name: /AI アシスタント/ });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const labelledBy = dialog.getAttribute("aria-labelledby")!;
    expect(document.getElementById(labelledBy)).toHaveTextContent("AI アシスタント（デモ応答）");
    expect(dialog).toHaveAttribute("id", launcher().getAttribute("aria-controls")!);
  });

  it("provider が openai のときは（デモ応答）を出さない", async () => {
    chat = createChatFetch();
    chat.status(() => json(200, STATUS_OK));
    vi.stubGlobal("fetch", chat.mock);
    await openPanel();
    expect(screen.getByRole("heading", { name: "AI アシスタント" })).not.toHaveTextContent("デモ応答");
  });

  it("開くと入力欄にフォーカス。会話の一覧は role=log・aria-live=polite・aria-relevant=additions", async () => {
    await openPanel();
    expect(screen.getByRole("textbox")).toHaveFocus();
    const log = screen.getByRole("log");
    expect(log).toHaveAttribute("aria-live", "polite");
    expect(log).toHaveAttribute("aria-relevant", "additions");
    expect(log).toHaveAttribute("aria-busy", "false");
    // 入力欄にはラベルがあり、残り文字数と注意書きに結ばれている
    const textbox = screen.getByRole("textbox", { name: /質問を入力/ });
    expect(textbox.getAttribute("aria-describedby")).toContain(screen.getByText("残り 300 文字").id);
    expect(screen.getByText(/氏名・住所・電話番号などは入力しないでください/)).toBeInTheDocument();
  });

  it("Tab はパネル内で循環する（最後 → 最初、最初 → 最後）", async () => {
    await openPanel();
    const dialog = screen.getByRole("dialog");
    const focusables = Array.from(
      dialog.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), textarea:not([disabled]), [tabindex="0"]'),
    );
    expect(focusables.length).toBeGreaterThanOrEqual(4);
    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(first).toHaveFocus();

    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });

  it("Escape で閉じ、開いたボタン（ランチャー）にフォーカスが戻る", async () => {
    await openPanel();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(launcher()).toHaveFocus();
    expect(launcher()).toHaveAttribute("aria-expanded", "false");
  });

  it("×ボタンで閉じてもランチャーにフォーカスが戻る。ランチャーを押しても閉じられる", async () => {
    await openPanel();
    fireEvent.click(screen.getByRole("button", { name: "閉じる" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(launcher()).toHaveFocus();

    fireEvent.click(launcher());
    await flush();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(launcher());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("送信中は role=log が aria-busy=true。パネルを閉じても応答は届き、開き直すと会話が残っている", async () => {
    await openPanel();
    let release!: (r: Response) => void;
    chat.messages(() => new Promise<Response>((r) => (release = r)));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "こんにちは" } });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));
    await flush();
    expect(screen.getByRole("log")).toHaveAttribute("aria-busy", "true");

    fireEvent.click(screen.getByRole("button", { name: "閉じる" }));
    await act(async () => release(json(200, recommendBody(1))));
    fireEvent.click(launcher());
    await flush();
    expect(screen.getByText("春先に羽織れる軽めの商品を選びました。")).toBeInTheDocument();
    expect(chat.calls("status")).toHaveLength(1); // 会話の途中で開き直しても status は取り直さない
  });
});
