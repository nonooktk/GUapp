import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearCookies,
  createChatFetch,
  json,
  recommendBody,
  renderChat,
  setCsrfCookie,
  STATUS_OK,
} from "./helpers/chat";

// テスト設計書 UT-WEB-AI-02: ChatProvider の状態遷移（設計仕様書 P2 追補d 3.3・6.3）。
// 閉→確認中→入力待ち→送信中→入力待ち／502・504・通信失敗→再送待ち／429→待機／409→往復上限／503 両方→利用不可／連続クリック。

let chat: ReturnType<typeof createChatFetch>;

beforeEach(() => {
  chat = createChatFetch();
  vi.stubGlobal("fetch", chat.mock);
  setCsrfCookie();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  clearCookies();
});

/** 保留中の応答を後から解決できる Promise */
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function openPanel() {
  fireEvent.click(screen.getByRole("button", { name: "AI アシスタントに相談する" }));
}
const input = () => screen.getByRole("textbox") as HTMLTextAreaElement;
const sendButton = () => screen.getByRole("button", { name: "送信" }) as HTMLButtonElement;

async function openReady() {
  chat.status(() => json(200, STATUS_OK));
  renderChat();
  openPanel();
  await flush();
}

function type(text: string) {
  fireEvent.change(input(), { target: { value: text } });
}

describe("UT-WEB-AI-02 ChatProvider の状態", () => {
  it("閉→確認中→入力待ち→送信中→入力待ち。送信中は二重送信されず、入力済みの文字は残る", async () => {
    const statusGate = deferred<Response>();
    chat.status(() => statusGate.promise);
    renderChat();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); // 閉じている

    openPanel();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("確認しています…")).toBeInTheDocument(); // 確認中
    expect(input()).toBeDisabled();
    expect(sendButton()).toBeDisabled();

    await act(async () => statusGate.resolve(json(200, STATUS_OK)));
    expect(input()).toBeEnabled(); // 入力待ち
    expect(screen.getByText("商品選びと、よくある質問にお答えします。")).toBeInTheDocument();
    expect(screen.getByText("あと 10 往復")).toBeInTheDocument();
    expect(sendButton()).toBeDisabled(); // 入力が無いうちは無効

    const gate = deferred<Response>();
    chat.messages(() => gate.promise);
    type("春に羽織れる軽いアウターが欲しいです");
    const send = sendButton();
    expect(send).toBeEnabled();
    fireEvent.click(send);
    fireEvent.click(send); // 連続クリック
    fireEvent.submit(input().closest("form")!); // フォームの再送信
    await flush();

    // 送信中: 利用者の吹き出し＋考え中。入力は無効だが文字は残る
    expect(screen.getByText("春に羽織れる軽いアウターが欲しいです", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("考え中…")).toBeInTheDocument();
    expect(screen.getByRole("log")).toHaveAttribute("aria-busy", "true");
    expect(input()).toBeDisabled();
    expect(input().value).toBe("春に羽織れる軽いアウターが欲しいです");
    expect(chat.calls("messages")).toHaveLength(1);

    await act(async () => gate.resolve(json(200, recommendBody(1))));
    expect(screen.getByText("春先に羽織れる軽めの商品を選びました。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /薄手パーカー/ })).toHaveAttribute("href", "/products/12");
    expect(screen.queryByText("考え中…")).not.toBeInTheDocument();
    expect(screen.getByRole("log")).toHaveAttribute("aria-busy", "false");
    expect(input()).toBeEnabled();
    expect(input().value).toBe(""); // 成功したら入力欄を空にする
    expect(screen.getByText("あと 9 往復")).toBeInTheDocument();
    expect(chat.calls("messages")).toHaveLength(1);
  });

  it("質問の例ボタンは固定の文を送信する", async () => {
    await openReady();
    chat.messages(() => json(200, recommendBody(1)));
    fireEvent.click(screen.getByRole("button", { name: "送料は？" }));
    await flush();
    const [, init] = chat.calls("messages")[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ message: "送料は？", product_id: null });
  });

  it.each([
    ["502 llm_error", () => json(502, { code: "llm_error" })],
    ["504 llm_timeout", () => json(504, { code: "llm_timeout" })],
    ["503 upstream_unavailable", () => json(503, { code: "upstream_unavailable" })],
  ])("%s → 再送待ち: 入力した文が残り、再送で送り直せる", async (_name, failing) => {
    await openReady();
    chat.messages(failing, () => json(200, recommendBody(1)));
    type("黒のパーカーが欲しいです");
    fireEvent.click(sendButton());
    await flush();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("うまく答えられませんでした。もう一度送るか、よくある質問をご覧ください");
    expect(screen.getByRole("link", { name: "よくある質問" })).toHaveAttribute("href", "/contents/faq");
    expect(screen.getByRole("link", { name: "企業情報" })).toHaveAttribute("href", "/contents/company");
    expect(input()).toBeEnabled();
    expect(input().value).toBe("黒のパーカーが欲しいです");
    expect(screen.queryByText("黒のパーカーが欲しいです", { selector: "p" })).not.toBeInTheDocument(); // 送れなかった吹き出しは外す

    fireEvent.click(screen.getByRole("button", { name: "再送" }));
    await flush();
    expect(chat.calls("messages")).toHaveLength(2);
    const bodies = chat.calls("messages").map(([, init]) => JSON.parse((init as RequestInit).body as string));
    expect(bodies[1]).toEqual(bodies[0]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("春先に羽織れる軽めの商品を選びました。")).toBeInTheDocument();
  });

  it("通信失敗（fetch の例外）も再送待ち", async () => {
    await openReady();
    chat.messages(() => {
      throw new TypeError("network down");
    });
    type("こんにちは");
    fireEvent.click(sendButton());
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent("うまく答えられませんでした");
    expect(screen.getByRole("button", { name: "再送" })).toBeInTheDocument();
    expect(input().value).toBe("こんにちは");
  });

  it("429 → 待機: Retry-After の秒数だけ送信が無効になり、過ぎると有効に戻る", async () => {
    vi.useFakeTimers();
    await openReady();
    chat.messages(() => json(429, { code: "rate_limited" }, { "Retry-After": "90" }));
    type("こんにちは");
    fireEvent.click(sendButton());
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent("短い時間に多くの質問が送られました。90 秒後にもう一度お試しください");
    expect(input()).toBeEnabled();
    expect(sendButton()).toBeDisabled();

    await act(async () => {
      vi.advanceTimersByTime(89_000);
    });
    expect(sendButton()).toBeDisabled();
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(sendButton()).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("409 turn_limit → 往復上限: 入力と送信が無効。「新しい相談を始める」で Cookie と会話を消して入力待ちに戻る", async () => {
    await openReady();
    chat.messages(() => json(200, recommendBody(10)), () => json(409, { code: "turn_limit", limit: 10 }));
    chat.reset(() => json(200, { ok: true }));

    type("1 回目");
    fireEvent.click(sendButton());
    await flush();
    expect(screen.getByText("あと 0 往復")).toBeInTheDocument();

    type("11 回目");
    fireEvent.click(sendButton());
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent("この相談の上限（10 往復）に達しました。新しい相談を始めてください");
    expect(input()).toBeDisabled();
    expect(sendButton()).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "新しい相談を始める" }));
    await flush();
    const [url, init] = chat.calls("reset")[0] as [string, RequestInit];
    expect(url).toBe("/api/chat/reset");
    expect(init.method).toBe("POST");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(input()).toBeEnabled();
    expect(screen.queryByText("春先に羽織れる軽めの商品を選びました。")).not.toBeInTheDocument(); // 会話が空
    expect(screen.getByText("あと 10 往復")).toBeInTheDocument();
  });

  it.each([
    ["chat_daily_limit", "現在利用できません。しばらくしてからお試しください"],
    ["chat_unavailable", "現在利用できません"],
  ])("503 %s → 利用不可: 入力が無効で、よくある質問へのリンクが出る", async (code, text) => {
    await openReady();
    chat.messages(() => json(503, { code }));
    type("こんにちは");
    fireEvent.click(sendButton());
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent(text);
    expect(input()).toBeDisabled();
    expect(sendButton()).toBeDisabled();
    expect(screen.getByRole("link", { name: "よくある質問" })).toHaveAttribute("href", "/contents/faq");
    expect(screen.queryByRole("button", { name: "再送" })).not.toBeInTheDocument();
  });

  it("status が unavailable → 確認中のあと利用不可。開き直すと status を確認し直す", async () => {
    chat.status(
      () => json(200, { ...STATUS_OK, available: false, reason: "daily_limit", provider: "none" }),
      () => json(200, STATUS_OK),
    );
    renderChat();
    openPanel();
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent("現在利用できません。しばらくしてからお試しください");
    expect(input()).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "閉じる" }));
    openPanel();
    await flush();
    expect(chat.calls("status")).toHaveLength(2);
    expect(input()).toBeEnabled();
  });

  it("status の取得に失敗したら利用不可として案内する", async () => {
    chat.status(() => json(503, { code: "upstream_unavailable" }));
    renderChat();
    openPanel();
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent("現在利用できません");
    expect(input()).toBeDisabled();
  });

  it("400（形の不正）は入力欄の直下に理由を出し、入力待ちのまま", async () => {
    await openReady();
    chat.messages(() => json(400, { code: "validation_error", fields: [{ name: "message", reason: "too_long" }] }));
    type("あ");
    fireEvent.click(sendButton());
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent("質問は 300 文字以内で入力してください");
    expect(input()).toBeEnabled();
    expect(input().value).toBe("あ");
  });

  it("個人情報を伏せた応答（notice=masked）は利用者の吹き出しの下に注記を出す", async () => {
    await openReady();
    chat.messages(() => json(200, recommendBody(1, { notice: "masked" })));
    type("メールは a@example.com です");
    fireEvent.click(sendButton());
    await flush();
    expect(screen.getByText("個人情報らしき文字列は伏せて処理しました")).toBeInTheDocument();
  });

  it("入力欄は 301 文字目を受け付けない（コードポイント数。絵文字は 1 文字）", async () => {
    await openReady();
    type("あ".repeat(305));
    expect(Array.from(input().value)).toHaveLength(300);
    expect(screen.getByText("残り 0 文字")).toBeInTheDocument();
    type("😀".repeat(301));
    expect(Array.from(input().value)).toHaveLength(300);
  });

  it("会話は sessionStorage・localStorage に保存しない", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    await openReady();
    chat.messages(() => json(200, recommendBody(1)));
    type("こんにちは");
    fireEvent.click(sendButton());
    await flush();
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });
});
