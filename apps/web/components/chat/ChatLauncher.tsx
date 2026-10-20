"use client";

import { CHAT_LAUNCHER_ID, CHAT_PANEL_ID, useChat } from "@/components/chat/ChatProvider";

/**
 * チャットを開く丸いボタン（設計仕様書 P2 追補d 6.1・DS-SCR-013、テスト UT-WEB-AI-03）。
 * 直径 56px。375px 以上 640px 未満は右 16px・下 96px（商品詳細の下部固定バー〔約 76px・z-30〕と重ならない）、
 * 640px 以上は右 24px・下 24px。z-index は 40（ヘッダーと同格、固定バー 30 より上、トースト 50 より下）。
 * `aria-label`・`aria-expanded`・`aria-controls`。フォーカス枠は共通（globals.css の :focus-visible）。
 */
export default function ChatLauncher() {
  const { open, openChat, closeChat } = useChat();
  return (
    <button
      id={CHAT_LAUNCHER_ID}
      type="button"
      aria-label="AI アシスタントに相談する"
      aria-expanded={open}
      aria-controls={CHAT_PANEL_ID}
      aria-haspopup="dialog"
      onClick={() => (open ? closeChat() : openChat())}
      className="fixed bottom-24 right-4 z-40 flex size-14 flex-col items-center justify-center gap-0.5 rounded-pill bg-primary text-primary-fg transition-colors hover:bg-primary-hover sm:bottom-6 sm:right-6"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
        <path d="M4 5h16v11H9l-5 4z" />
      </svg>
      <span aria-hidden="true" className="text-xs font-bold leading-none">
        相談
      </span>
    </button>
  );
}
