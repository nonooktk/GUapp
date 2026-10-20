"use client";

import Link from "next/link";
import ChatProductCard from "@/components/chat/ChatProductCard";
import { useChat, type ChatLogItem } from "@/components/chat/ChatProvider";
import { CHAT_MASKED_NOTICE } from "@/lib/chat-messages";

/**
 * 吹き出し 1 つ（設計仕様書 P2 追補d 6.2・6.6・7.1、テスト UT-WEB-AI-06）。
 * 本文は**プレーンテキスト**として描く（React の既定のエスケープだけ。生の HTML を差し込む API は使わない）。
 * 改行は `white-space: pre-line` で保つ。リンクはサーバーが組み立てたもの（商品カード・出典・案内）だけで、
 * 本文に含まれる URL や Markdown のリンクは文字のまま表示する。
 */

const linkClass = "inline-flex min-h-11 items-center text-sm text-fg underline";

export default function ChatMessageItem({ item }: { item: ChatLogItem }) {
  const { imageBaseUrl, closeIfSheet } = useChat();
  const isUser = item.role === "user";
  const reply = item.reply;

  return (
    <li className={`flex flex-col gap-2 ${isUser ? "items-end" : "items-start"}`}>
      <span className="sr-only">{isUser ? "あなた" : "AI アシスタント"}</span>
      <p
        className={`max-w-[85%] whitespace-pre-line break-words rounded-sm px-3 py-2 text-sm ${
          isUser ? "bg-primary text-primary-fg" : "bg-line/60 text-fg"
        }`}
      >
        {item.text}
      </p>
      {isUser && item.masked && <p className="text-xs text-fg-muted">{CHAT_MASKED_NOTICE}</p>}

      {reply && reply.products.length > 0 && (
        <ul aria-label="おすすめの商品" className="w-full space-y-2">
          {reply.products.map((p) => (
            <li key={p.id}>
              <ChatProductCard product={p} imageBaseUrl={imageBaseUrl} onNavigate={closeIfSheet} />
            </li>
          ))}
        </ul>
      )}

      {reply && reply.sources.length > 0 && (
        <p className="text-sm text-fg-muted">
          出典:{" "}
          {reply.sources.map((s) => (
            <Link key={s.href} href={s.href} onClick={closeIfSheet} className={linkClass}>
              {s.label}
            </Link>
          ))}
        </p>
      )}

      {reply && reply.guide.length > 0 && (
        <ul aria-label="案内" className="flex flex-wrap gap-x-4">
          {reply.guide.map((g) => (
            <li key={g.href}>
              <Link href={g.href} onClick={closeIfSheet} className={linkClass}>
                {g.label}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
