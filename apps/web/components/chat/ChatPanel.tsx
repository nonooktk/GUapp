"use client";

import Link from "next/link";
import { useEffect, useId, useRef } from "react";
import Button from "@/components/Button";
import ChatMessageItem from "@/components/chat/ChatMessageItem";
import { CHAT_LAUNCHER_ID, CHAT_PANEL_ID, useChat } from "@/components/chat/ChatProvider";
import { CHAT_EXAMPLES, CHAT_GREETING, CHAT_GUIDE_LINKS, CHAT_NOTICE_TEXT } from "@/lib/chat-messages";
import { CHAT_MESSAGE_MAX_CHARS, countCodePoints } from "@/lib/chat-validation";

/**
 * チャットのパネル本体（設計仕様書 P2 追補d 6.2〜6.4・DS-SCR-013、テスト UT-WEB-AI-04）。
 * - 640px 未満は画面全体を覆うシート（高さ 100dvh）、640px 以上は右下に幅 380px・高さ 560px のパネル（ランチャーの上）
 * - `role="dialog"`・`aria-modal`・`aria-labelledby`。開いたら入力欄へフォーカス、Tab はパネル内で循環、Escape で閉じ、
 *   閉じたら開いた元のボタン（無ければランチャー）へフォーカスを戻す（AllMenu・ConfirmDialog と同じ規則）
 * - 会話の一覧は `role="log"`・`aria-live="polite"`・`aria-relevant="additions"`、送信中は `aria-busy`
 * - 失敗の表示は `role="alert"`（⚠ ＋ 文言。色だけで伝えない）。開閉の動きは付けない（prefers-reduced-motion への配慮）
 */

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), [tabindex="0"]';

export default function ChatPanel() {
  const chat = useChat();
  const { open, phase, status, items, draft, failure, fieldError, waitSec, turnsUsed, turnsLimit, product } = chat;
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const inputId = useId();
  const countId = useId();
  const noticeId = useId();
  const errorId = useId();

  const { closeChat } = chat;

  // 開いている間: Escape で閉じる。閉じたら開いた元のボタン（無ければランチャー）へフォーカスを戻す。375px のシートは背面のスクロールを止める
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeChat();
      }
    };
    document.addEventListener("keydown", onKey);

    const isSheet = typeof window.matchMedia === "function" && window.matchMedia("(max-width: 639px)").matches;
    const previousOverflow = document.body.style.overflow;
    if (isSheet) document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKey);
      if (isSheet) document.body.style.overflow = previousOverflow;
      const target =
        opener && opener !== document.body && opener.isConnected && !panel?.contains(opener)
          ? opener
          : document.getElementById(CHAT_LAUNCHER_ID);
      target?.focus();
    };
  }, [open, closeChat]);

  // フォーカスの置き場所: 入力できる状態なら入力欄、そうでなければパネル自身（無効になった要素に残さない）
  const inputEnabled = phase === "ready" || phase === "retry" || phase === "wait";
  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;
    const active = document.activeElement as HTMLElement | null;
    const inside = !!active && active !== panel && panel.contains(active);
    const unusable = !!active && (active as HTMLButtonElement).disabled === true;
    if (inside && !unusable) return;
    if (inputEnabled) inputRef.current?.focus();
    else panel.focus();
  }, [open, phase, inputEnabled]);

  // 新しい吹き出しが増えたら末尾までスクロール
  const lastItemId = items.length > 0 ? items[items.length - 1].id : 0;
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [open, lastItemId, phase]);

  if (!open) return null;

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab" || !panelRef.current) return;
    const focusables = panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE);
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === panelRef.current)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || active === panelRef.current)) {
      e.preventDefault();
      first.focus();
    }
  };

  const onDraftChange = (value: string) => {
    // 301 文字目は受け付けない（コードポイント数。絵文字は 1 文字）
    const chars = Array.from(value);
    chat.setDraft(chars.length > CHAT_MESSAGE_MAX_CHARS ? chars.slice(0, CHAT_MESSAGE_MAX_CHARS).join("") : value);
  };

  const remainingChars = Math.max(0, CHAT_MESSAGE_MAX_CHARS - countCodePoints(draft));
  const remainingTurns = Math.max(0, turnsLimit - turnsUsed);
  const sending = phase === "sending";
  const canSend = (phase === "ready" || phase === "retry") && draft.trim() !== "";
  const isStub = status?.provider === "stub";
  const showGreeting = phase !== "checking" && phase !== "unavailable";
  const guideLinks = failure?.kind === "unavailable" ? CHAT_GUIDE_LINKS.slice(0, 1) : CHAT_GUIDE_LINKS;
  const linkClass = "inline-flex min-h-11 items-center text-sm text-fg underline";

  return (
    <div className="fixed inset-0 z-[60] bg-overlay sm:inset-auto sm:bottom-24 sm:right-6 sm:bg-transparent">
      <div
        id={CHAT_PANEL_ID}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="flex h-dvh w-full flex-col bg-bg focus:outline-none sm:h-[560px] sm:max-h-[calc(100dvh-7rem)] sm:w-[380px] sm:rounded-sm sm:border sm:border-line sm:shadow-modal"
      >
        <div className="flex min-h-14 shrink-0 items-center justify-between gap-2 border-b border-line pl-4 pr-2">
          <h2 id={titleId} className="text-base font-bold tracking-heading text-fg">
            AI アシスタント
            {isStub && <span className="font-normal text-fg-muted">（デモ応答）</span>}
          </h2>
          <div className="flex shrink-0 items-center">
            <button
              type="button"
              onClick={() => void chat.reset()}
              disabled={sending || phase === "checking" || phase === "unavailable"}
              className="inline-flex min-h-11 items-center rounded-pill px-3 text-sm text-fg hover:bg-line disabled:text-disabled-fg disabled:hover:bg-transparent"
            >
              新しい相談
            </button>
            <button
              type="button"
              onClick={closeChat}
              aria-label="閉じる"
              className="inline-flex size-11 items-center justify-center rounded-pill text-fg hover:bg-line"
            >
              <span aria-hidden="true" className="text-xl leading-none">
                ×
              </span>
            </button>
          </div>
        </div>

        {product && (
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line bg-line/40 pl-4 pr-2 text-sm">
            <p className="min-w-0 truncate">{product.name} について質問中</p>
            <button
              type="button"
              onClick={chat.clearProduct}
              aria-label="質問の対象を外す"
              className="inline-flex size-11 shrink-0 items-center justify-center rounded-pill hover:bg-line"
            >
              <span aria-hidden="true" className="text-lg leading-none">
                ×
              </span>
            </button>
          </div>
        )}

        <div
          ref={logRef}
          role="log"
          aria-label="会話"
          aria-live="polite"
          aria-relevant="additions"
          aria-busy={sending}
          tabIndex={0}
          className="min-h-0 flex-1 overflow-y-auto px-4 py-3"
        >
          {phase === "checking" && <p className="text-sm text-fg-muted">確認しています…</p>}
          {showGreeting && (
            <div className="mb-3 space-y-2">
              <p className="text-sm">{CHAT_GREETING}</p>
              {items.length === 0 && (
                <ul aria-label="質問の例" className="flex flex-wrap gap-2">
                  {CHAT_EXAMPLES.map((example) => (
                    <li key={example}>
                      <button
                        type="button"
                        disabled={phase !== "ready"}
                        onClick={() => {
                          chat.setDraft(example);
                          void chat.send(example);
                        }}
                        className="inline-flex min-h-11 items-center rounded-pill border border-fg-muted bg-bg px-3 text-sm text-fg hover:bg-line disabled:border-disabled-bg disabled:text-disabled-fg disabled:hover:bg-bg"
                      >
                        {example}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {(items.length > 0 || sending) && (
            <ul className="space-y-3">
              {items.map((item) => (
                <ChatMessageItem key={item.id} item={item} />
              ))}
              {sending && <li className="text-sm text-fg-muted">考え中…</li>}
            </ul>
          )}
        </div>

        {failure && (
          <div role="alert" className="shrink-0 space-y-1 border-t border-line px-4 py-2">
            <p className="text-sm text-danger">
              <span aria-hidden="true">⚠ </span>
              {failure.message}
            </p>
            <div className="flex flex-wrap items-center gap-x-4">
              {failure.kind === "retry" && (
                <Button variant="secondary" size="md" onClick={() => void chat.resend()}>
                  再送
                </Button>
              )}
              {failure.kind === "turn_limit" && (
                <Button variant="primary" size="md" onClick={() => void chat.reset()}>
                  新しい相談を始める
                </Button>
              )}
              {(failure.kind === "retry" || failure.kind === "unavailable") &&
                guideLinks.map((l) => (
                  <Link key={l.href} href={l.href} onClick={chat.closeIfSheet} className={linkClass}>
                    {l.label}
                  </Link>
                ))}
            </div>
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (canSend) void chat.send(draft);
          }}
          className="shrink-0 border-t border-line px-4 py-3"
        >
          <div className="flex items-end gap-2">
            <div className="min-w-0 flex-1">
              <label htmlFor={inputId} className="sr-only">
                質問を入力（{CHAT_MESSAGE_MAX_CHARS} 文字まで）
              </label>
              <textarea
                id={inputId}
                ref={inputRef}
                rows={2}
                value={draft}
                disabled={!inputEnabled}
                onChange={(e) => onDraftChange(e.target.value)}
                onKeyDown={(e) => {
                  // Enter は改行。Ctrl／Cmd + Enter で送信
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    if (canSend) void chat.send(draft);
                  }
                }}
                placeholder={`質問を入力（${CHAT_MESSAGE_MAX_CHARS} 文字まで）`}
                aria-invalid={fieldError ? true : undefined}
                aria-describedby={`${countId} ${noticeId}${fieldError ? ` ${errorId}` : ""}`}
                className="w-full resize-none rounded-sm border border-fg-muted bg-bg px-3 py-2 text-base text-fg focus:border-fg aria-invalid:border-danger disabled:cursor-not-allowed disabled:bg-line/40 disabled:text-disabled-fg"
              />
            </div>
            <Button type="submit" variant="primary" size="md" disabled={!canSend || waitSec > 0} busy={sending} busyLabel="送信中…">
              送信
            </Button>
          </div>
          {fieldError && (
            <p id={errorId} role="alert" className="mt-1 text-sm text-danger">
              <span aria-hidden="true">⚠ </span>
              {fieldError}
            </p>
          )}
          <div className="mt-1 flex justify-between gap-2 text-xs text-fg-muted">
            <span id={countId}>残り {remainingChars} 文字</span>
            <span>あと {remainingTurns} 往復</span>
          </div>
          <p id={noticeId} className="mt-1 text-xs text-fg-muted">
            {CHAT_NOTICE_TEXT}
          </p>
        </form>
      </div>
    </div>
  );
}
