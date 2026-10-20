"use client";

import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { chatUnavailableMessage, describeChatFailure, chatValidationMessage, type ChatFailure } from "@/lib/chat-messages";
import { validateChatMessage } from "@/lib/chat-validation";
import { ChatApiError, getChatStatus, resetChat, sendChatMessage } from "@/lib/client/chat-api";
import type { ChatReply, ChatStatus } from "@/lib/types";

/**
 * AI アシスタントの共有状態（設計仕様書 P2 追補d 3.3・6.3・6.5・DS-DEC-102、テスト UT-WEB-AI-02・09）。
 * - 開閉、会話（吹き出し・商品カード）、画面の状態、商品詳細から渡される `product_id` の文脈を保持する
 * - 会話は**画面のメモリだけ**で持つ（sessionStorage などに保存しない。商品カードの価格が古くなるため）。再読み込みで消える
 * - 状態: 確認中 → 入力待ち ⇄ 送信中。送信の結果で 再送待ち／待機（429）／往復上限（409）／利用不可（503）へ
 * - 二重送信は ref で防ぐ（送信中は fetch を 1 回しか呼ばない）
 * - 商品の文脈は、開いた時点のパスにだけ有効（別のページへ移ったら外れる。別の商品について聞いてしまうのを防ぐ）
 * - `chat_token` は HttpOnly Cookie なので JS からは見えない。往復数・履歴は Cookie 側（api）が持つ
 */

export const CHAT_LAUNCHER_ID = "chat-launcher";
export const CHAT_PANEL_ID = "chat-panel";

export type ChatPhase = "checking" | "ready" | "sending" | "retry" | "wait" | "turn_limit" | "unavailable";

export interface ChatLogItem {
  id: number;
  role: "user" | "assistant";
  text: string;
  /** 利用者の吹き出し: 個人情報らしき文字列を伏せて処理した */
  masked?: boolean;
  /** AI の吹き出し: 商品カード・出典・案内リンクを含む応答 */
  reply?: ChatReply;
}

export interface ChatProductContext {
  id: number;
  name: string;
}

export interface OpenChatOptions {
  product?: ChatProductContext;
}

interface ChatContextValue {
  imageBaseUrl: string;
  open: boolean;
  phase: ChatPhase;
  status: ChatStatus | null;
  items: ChatLogItem[];
  draft: string;
  setDraft: (value: string) => void;
  /** 再送待ち・待機・往復上限・利用不可のときの表示（`role="alert"`） */
  failure: ChatFailure | null;
  /** 入力欄の直下に出す、形の不正（空・301 文字以上）の理由 */
  fieldError: string | null;
  /** 待機（429）の残り秒数 */
  waitSec: number;
  turnsUsed: number;
  turnsLimit: number;
  product: ChatProductContext | null;
  clearProduct: () => void;
  openChat: (options?: OpenChatOptions) => void;
  closeChat: () => void;
  /** 質問を送る。引数なしは入力欄の内容 */
  send: (text?: string) => Promise<void>;
  /** 直前に送った質問をもう一度送る */
  resend: () => Promise<void>;
  /** 「新しい相談」。Cookie と画面の会話を消す */
  reset: () => Promise<void>;
  /** 商品カード・案内リンクを押したとき。375px のシートは遷移先を隠すので閉じる */
  closeIfSheet: () => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

export function useChat(): ChatContextValue {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat は ChatProvider の内側で使ってください");
  return ctx;
}

const DEFAULT_TURNS_LIMIT = 10;
const RESET_FAILED_MESSAGE = "新しい相談を始められませんでした。もう一度お試しください";

export interface ChatProviderProps {
  children: ReactNode;
  /** 商品画像の配信ベース URL（公開 URL。サーバーの layout が渡す） */
  imageBaseUrl: string;
}

export function ChatProvider({ children, imageBaseUrl }: ChatProviderProps) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<ChatPhase>("checking");
  const [status, setStatus] = useState<ChatStatus | null>(null);
  const [items, setItems] = useState<ChatLogItem[]>([]);
  const [draft, setDraft] = useState("");
  const [failure, setFailure] = useState<ChatFailure | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [waitSec, setWaitSec] = useState(0);
  const [turnsUsed, setTurnsUsed] = useState(0);
  const [turnsLimit, setTurnsLimit] = useState(DEFAULT_TURNS_LIMIT);
  const [productCtx, setProductCtx] = useState<(ChatProductContext & { path: string | null }) | null>(null);

  const sendingRef = useRef(false);
  const lastTextRef = useRef("");
  const nextIdRef = useRef(1);
  const waitRemainingRef = useRef(0);

  const product = useMemo<ChatProductContext | null>(
    () => (productCtx && productCtx.path === pathname ? { id: productCtx.id, name: productCtx.name } : null),
    [productCtx, pathname],
  );

  // ---- 待機（429）: Retry-After の秒数が過ぎたら入力待ちへ戻す ----
  useEffect(() => {
    if (phase !== "wait") return;
    const timer = setInterval(() => {
      waitRemainingRef.current -= 1;
      setWaitSec(Math.max(0, waitRemainingRef.current));
      if (waitRemainingRef.current <= 0) {
        clearInterval(timer);
        setFailure(null);
        setPhase("ready");
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [phase]);

  // ---- 状態の確認（開いたとき） ----
  const checkStatus = useCallback(async () => {
    setPhase("checking");
    setFailure(null);
    try {
      const next = await getChatStatus();
      setStatus(next);
      setTurnsLimit(next.turns_limit > 0 ? next.turns_limit : DEFAULT_TURNS_LIMIT);
      if (next.available) {
        setPhase("ready");
      } else {
        setFailure({ kind: "unavailable", message: chatUnavailableMessage(next.reason) });
        setPhase("unavailable");
      }
    } catch {
      // 確認できないときは利用不可として案内する（次に開いたとき、もう一度確認する）
      setFailure({ kind: "unavailable", message: chatUnavailableMessage("disabled") });
      setPhase("unavailable");
    }
  }, []);

  const openChat = useCallback(
    (options?: OpenChatOptions) => {
      if (options?.product) setProductCtx({ ...options.product, path: pathname });
      setOpen(true);
      // 初回、または前回「利用不可」だったときだけ確認する（会話の途中で開き直しても、状態は変えない）
      if (status === null || phase === "unavailable") void checkStatus();
    },
    [pathname, status, phase, checkStatus],
  );

  const closeChat = useCallback(() => setOpen(false), []);

  const closeIfSheet = useCallback(() => {
    if (typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(max-width: 639px)").matches) {
      setOpen(false);
    }
  }, []);

  const clearProduct = useCallback(() => setProductCtx(null), []);

  // ---- 送信 ----
  const sendText = useCallback(
    async (raw: string) => {
      if (sendingRef.current) return;
      if (phase !== "ready" && phase !== "retry") return;

      const checked = validateChatMessage(raw);
      if (!checked.ok) {
        setFieldError(chatValidationMessage(checked.reason));
        return;
      }
      const text = checked.value;

      sendingRef.current = true;
      lastTextRef.current = text;
      const userId = nextIdRef.current++;
      setFieldError(null);
      setFailure(null);
      setItems((prev) => [...prev, { id: userId, role: "user", text }]);
      setPhase("sending");

      try {
        const res = await sendChatMessage({ message: text, productId: product?.id ?? null });
        const assistantId = nextIdRef.current++;
        setItems((prev) => [
          ...prev.map((item) => (item.id === userId && res.notice === "masked" ? { ...item, masked: true } : item)),
          { id: assistantId, role: "assistant", text: res.reply.message, reply: res.reply },
        ]);
        setTurnsUsed(res.turns_used);
        setTurnsLimit(res.turns_limit > 0 ? res.turns_limit : DEFAULT_TURNS_LIMIT);
        setDraft("");
        setPhase("ready");
      } catch (err) {
        const failed = err instanceof ChatApiError ? describeChatFailure(err.status, err.body, err.retryAfterSec) : describeChatFailure(0, null);
        // 送れなかった質問の吹き出しは外す（文は入力欄に残してあるので、再送か修正ができる）
        setItems((prev) => prev.filter((item) => item.id !== userId));
        setDraft(text);
        if (failed.kind === "validation") {
          setFieldError(failed.message);
          setPhase("ready");
        } else if (failed.kind === "wait") {
          waitRemainingRef.current = failed.waitSec ?? 0;
          setWaitSec(failed.waitSec ?? 0);
          setFailure(failed);
          setPhase("wait");
        } else if (failed.kind === "turn_limit") {
          if (failed.limit) {
            setTurnsLimit(failed.limit);
            setTurnsUsed(failed.limit);
          }
          setFailure(failed);
          setPhase("turn_limit");
        } else if (failed.kind === "unavailable") {
          setFailure(failed);
          setPhase("unavailable");
        } else {
          setFailure(failed);
          setPhase("retry");
        }
      } finally {
        sendingRef.current = false;
      }
    },
    [phase, product],
  );

  const send = useCallback((text?: string) => sendText(text ?? draft), [sendText, draft]);
  const resend = useCallback(() => sendText(lastTextRef.current || draft), [sendText, draft]);

  const reset = useCallback(async () => {
    // 送信中・確認中・利用不可では始め直せない（利用不可の解除は開き直したときの status 確認で行う）
    if (sendingRef.current || phase === "checking" || phase === "unavailable") return;
    try {
      await resetChat();
    } catch {
      // 往復上限の表示は残し（「新しい相談を始める」を押し直せる）、文言だけ足す
      setFailure((current) =>
        current?.kind === "turn_limit"
          ? { ...current, message: `${current.message}。${RESET_FAILED_MESSAGE}` }
          : { kind: "notice", message: RESET_FAILED_MESSAGE },
      );
      return;
    }
    setItems([]);
    setDraft("");
    setFailure(null);
    setFieldError(null);
    setTurnsUsed(0);
    lastTextRef.current = "";
    setPhase("ready");
  }, [phase]);

  const value = useMemo<ChatContextValue>(
    () => ({
      imageBaseUrl,
      open,
      phase,
      status,
      items,
      draft,
      setDraft,
      failure,
      fieldError,
      waitSec,
      turnsUsed,
      turnsLimit,
      product,
      clearProduct,
      openChat,
      closeChat,
      send,
      resend,
      reset,
      closeIfSheet,
    }),
    [imageBaseUrl, open, phase, status, items, draft, failure, fieldError, waitSec, turnsUsed, turnsLimit, product, clearProduct, openChat, closeChat, send, resend, reset, closeIfSheet],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}
