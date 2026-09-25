import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Header from "@/components/Header";

// 設計仕様書 P2 追補a 6.1: 375px は検索アイコンをタップするとオーバーレイの検索パネルが開く
// （AllMenu と同じ「オーバーレイ＋フォーカストラップ＋Escape で閉じる」パターン）。

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

function openSearch() {
  const button = screen.getByRole("button", { name: "検索" });
  fireEvent.click(button);
  return button;
}

describe("SearchPanel（モバイル検索パネル）", () => {
  it("初期状態は閉じていて aria-expanded=false", () => {
    render(<Header cartCount={0} />);
    const button = screen.getByRole("button", { name: "検索" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("検索アイコンを押すと開き、aria-expanded=true になり入力欄にフォーカスが移る", () => {
    render(<Header cartCount={0} />);
    const button = openSearch();
    expect(button).toHaveAttribute("aria-expanded", "true");
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog.id).toBe(button.getAttribute("aria-controls"));
    const inputs = screen.getAllByRole("combobox");
    expect(inputs[inputs.length - 1]).toHaveFocus();
  });

  it("閉じるボタンで閉じ、検索アイコンにフォーカスが戻る", () => {
    render(<Header cartCount={0} />);
    const button = openSearch();
    fireEvent.click(screen.getByRole("button", { name: "検索を閉じる" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
  });

  it("背景クリックで閉じ、検索アイコンにフォーカスが戻る", () => {
    render(<Header cartCount={0} />);
    const button = openSearch();
    fireEvent.click(screen.getByTestId("search-panel-overlay"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it("入力欄が空の状態で Escape を押すとパネルごと閉じ、検索アイコンへフォーカスが戻る", () => {
    render(<Header cartCount={0} />);
    const button = openSearch();
    const inputs = screen.getAllByRole("combobox");
    fireEvent.keyDown(inputs[inputs.length - 1], { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it("候補が開いている状態で Escape を押すと候補だけ閉じ、パネルは開いたまま（回帰: 1 回の Escape でパネルまで閉じない）", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items: [{ id: 1, name: "パーカーA" }] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(<Header cartCount={0} />);
    openSearch();
    const inputs = screen.getAllByRole("combobox");
    const panelInput = inputs[inputs.length - 1];
    fireEvent.change(panelInput, { target: { value: "パ" } });
    await waitFor(() => expect(screen.getByRole("option")).toBeInTheDocument());

    fireEvent.keyDown(panelInput, { key: "Escape" });
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument(); // パネルはまだ開いている

    // 候補が閉じた状態でもう一度 Escape を押すと、今度はパネルごと閉じる
    fireEvent.keyDown(panelInput, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
