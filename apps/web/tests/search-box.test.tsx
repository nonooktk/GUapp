import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SearchBox from "@/components/SearchBox";
import type { SuggestResponse } from "@/lib/types";

/**
 * ST-F003-05／DS-API-004a に対応するサジェストのキーボード操作・combobox の aria 属性を確認する。
 * DS-PRC-004a: 入力から 300ms デバウンスして BFF（/api/search/suggest）を呼ぶ。
 */

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

function suggestBody(names: string[]): SuggestResponse {
  return { items: names.map((name, i) => ({ id: i + 1, name })) };
}

function mockFetchOnce(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  push.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

async function typeAndWaitForSuggestions(input: HTMLElement, text: string, names: string[]) {
  fetchMock.mockResolvedValue(mockFetchOnce(suggestBody(names)));
  fireEvent.change(input, { target: { value: text } });
  await waitFor(() => expect(fetchMock).toHaveBeenCalled(), { timeout: 1000 });
  if (names.length > 0) {
    await waitFor(() => expect(screen.getAllByRole("option")).toHaveLength(names.length));
  }
}

describe("SearchBox（DS-API-004a・combobox パターン）", () => {
  it("role=combobox・aria-expanded・aria-controls・aria-autocomplete を持つ", () => {
    render(<SearchBox />);
    const input = screen.getByRole("combobox", { name: "商品を検索" });
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveAttribute("aria-autocomplete", "list");
    expect(input).toHaveAttribute("aria-controls");
  });

  it("入力から 300ms デバウンスしてサジェストを取得し、ドロップダウンに表示する", async () => {
    render(<SearchBox />);
    const input = screen.getByRole("combobox");
    await typeAndWaitForSuggestions(input, "パ", ["パーカーA", "パーカーB"]);

    const url = fetchMock.mock.calls[0]?.[0] as string;
    expect(url).toContain("/api/search/suggest?q=");
    expect(screen.getByRole("listbox", { name: "検索候補" })).toBeInTheDocument();
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["パーカーA", "パーカーB"]);
  });

  it("↓キーで候補を順に移動し、aria-activedescendant が追従する", async () => {
    render(<SearchBox />);
    const input = screen.getByRole("combobox");
    await typeAndWaitForSuggestions(input, "パ", ["パーカーA", "パーカーB"]);

    fireEvent.keyDown(input, { key: "ArrowDown" });
    const first = screen.getAllByRole("option")[0];
    expect(input).toHaveAttribute("aria-activedescendant", first.id);
    expect(first).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(input, { key: "ArrowDown" });
    const second = screen.getAllByRole("option")[1];
    expect(input).toHaveAttribute("aria-activedescendant", second.id);

    // 末尾から ↓ でさらに押すと先頭へ循環する
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant", first.id);

    // ↑ で末尾へ循環する
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(input).toHaveAttribute("aria-activedescendant", second.id);
  });

  it("候補を選んでいない状態で Enter → 入力値のまま /search?q=... へ遷移する", async () => {
    render(<SearchBox />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "パーカー" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/search?q=%E3%83%91%E3%83%BC%E3%82%AB%E3%83%BC");
  });

  it("↓で候補をハイライトして Enter → その候補名で /search?q=... へ遷移する", async () => {
    render(<SearchBox />);
    const input = screen.getByRole("combobox");
    await typeAndWaitForSuggestions(input, "パ", ["パーカーA", "パーカーB"]);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(push).toHaveBeenCalledWith(`/search?q=${encodeURIComponent("パーカーA")}`);
  });

  it("候補をクリックして選択すると /search?q=... へ遷移する", async () => {
    render(<SearchBox />);
    const input = screen.getByRole("combobox");
    await typeAndWaitForSuggestions(input, "パ", ["パーカーA"]);
    fireEvent.mouseDown(screen.getByRole("option", { name: "パーカーA" }));
    expect(push).toHaveBeenCalledWith(`/search?q=${encodeURIComponent("パーカーA")}`);
  });

  it("候補が開いている状態で Escape を押すと候補だけ閉じる（遷移しない・onEscape は呼ばれない）", async () => {
    const onEscape = vi.fn();
    render(<SearchBox onEscape={onEscape} />);
    const input = screen.getByRole("combobox");
    await typeAndWaitForSuggestions(input, "パ", ["パーカーA"]);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onEscape).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("候補が閉じている状態で Escape を押すと onEscape が呼ばれる（モバイルパネルを閉じる用途）", () => {
    const onEscape = vi.fn();
    render(<SearchBox onEscape={onEscape} />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onEscape).toHaveBeenCalledTimes(1);
  });

  it("空文字にするとドロップダウンを閉じる（BFF を呼ばない）", async () => {
    render(<SearchBox />);
    const input = screen.getByRole("combobox");
    await typeAndWaitForSuggestions(input, "パ", ["パーカーA"]);
    fetchMock.mockClear();
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 350));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
