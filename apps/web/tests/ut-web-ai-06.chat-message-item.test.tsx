import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ChatMessageItem from "@/components/chat/ChatMessageItem";
import { ChatProvider, type ChatLogItem } from "@/components/chat/ChatProvider";
import { IMAGE_BASE } from "./helpers/chat";

// テスト設計書 UT-WEB-AI-06: LLM の文章はプレーンテキストとして描く（HTML・URL・Markdown は文字のまま）。
// リンクはサーバーが組み立てたもの（商品カード・出典・案内）だけ。設計仕様書 P2 追補d 6.6・7.1。

function renderItem(item: ChatLogItem) {
  return render(
    <ChatProvider imageBaseUrl={IMAGE_BASE}>
      <ul>
        <ChatMessageItem item={item} />
      </ul>
    </ChatProvider>,
  );
}

describe("UT-WEB-AI-06 ChatMessageItem", () => {
  const evil = "<img src=x onerror=alert(1)>\nhttp://evil.example\n[クリック](https://evil.example)";

  it("HTML・URL・Markdown のリンクは文字として表示され、要素にならない。リンク要素は生成されない", () => {
    const { container } = renderItem({ id: 1, role: "assistant", text: evil });
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    const bubble = screen.getByText((_, el) => el?.tagName === "P" && el.textContent === evil);
    expect(bubble).toBeInTheDocument();
  });

  it("改行は保持される（white-space: pre-line）", () => {
    renderItem({ id: 1, role: "assistant", text: "1 行目\n2 行目" });
    const bubble = screen.getByText((_, el) => el?.tagName === "P" && el.textContent === "1 行目\n2 行目");
    expect(bubble.className).toContain("whitespace-pre-line");
  });

  it("利用者の吹き出し: 伏せて処理した場合だけ注記を出す", () => {
    const { unmount } = renderItem({ id: 1, role: "user", text: "[メール] です", masked: true });
    expect(screen.getByText("個人情報らしき文字列は伏せて処理しました")).toBeInTheDocument();
    unmount();
    renderItem({ id: 2, role: "user", text: "こんにちは" });
    expect(screen.queryByText("個人情報らしき文字列は伏せて処理しました")).not.toBeInTheDocument();
  });

  it("リンクは出典・案内・商品カードのサーバー組み立て分だけ", () => {
    const { container } = renderItem({
      id: 1,
      role: "assistant",
      text: "よくある質問をご覧ください。",
      reply: {
        intent: "out_of_scope",
        message: "x",
        products: [],
        sources: [{ label: "よくある質問", href: "/contents/faq" }],
        guide: [
          { label: "よくある質問", href: "/contents/faq" },
          { label: "企業情報", href: "/contents/company" },
        ],
      },
    });
    const hrefs = Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/contents/faq", "/contents/faq", "/contents/company"]);
  });

  it("生の HTML を差し込む API が、チャットのソースに 0 件", () => {
    const roots = ["components/chat", "lib/client/chat-api.ts", "lib/chat-messages.ts", "lib/chat-validation.ts", "lib/server/chat-proxy.ts"];
    const files: string[] = [];
    const walk = (p: string) => {
      const abs = path.resolve(import.meta.dirname, "..", p);
      if (statSync(abs).isDirectory()) readdirSync(abs).forEach((f) => walk(path.join(p, f)));
      else files.push(abs);
    };
    roots.forEach(walk);
    expect(files.length).toBeGreaterThanOrEqual(10);
    for (const f of files) expect(readFileSync(f, "utf8"), f).not.toContain("dangerouslySetInnerHTML");
  });
});
