import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CartProvider } from "@/components/CartProvider";
import PurchasePanel, { resolveVariant } from "@/components/PurchasePanel";
import { ToastProvider } from "@/components/Toast";
import type { Variant } from "@/lib/types";

// テスト設計書 UT-WEB-08（在庫切れ表示）・UT-WEB-07（固定バーの追従）。設計仕様書 6.5・AT-03
const variants: Variant[] = [
  { variant_id: 1, color: "黒", size: "S", in_stock: true },
  { variant_id: 2, color: "黒", size: "M", in_stock: false }, // V-STOCK0
  { variant_id: 3, color: "白", size: "S", in_stock: true },
  { variant_id: 4, color: "白", size: "M", in_stock: true },
];

function renderPanel() {
  return render(
    <ToastProvider>
      <CartProvider hasCartCookie={false}>
        <PurchasePanel productId={1} price={1990} colors={["黒", "白"]} sizes={["S", "M"]} variants={variants} />
      </CartProvider>
    </ToastProvider>,
  );
}

/** 固定バー側ではなく、パネル内の追加ボタン（同じ testid が 2 つあるので最初＝パネル内を使う） */
const addButtons = () => screen.getAllByTestId("add-to-cart") as HTMLButtonElement[];

describe("UT-WEB-08 resolveVariant", () => {
  it("色とサイズの組合せから variant を返す。未選択・該当なしは null", () => {
    expect(resolveVariant(variants, "黒", "M")?.variant_id).toBe(2);
    expect(resolveVariant(variants, "黒", null)).toBeNull();
    expect(resolveVariant(variants, "赤", "S")).toBeNull();
  });
});

describe("UT-WEB-08 PurchasePanel", () => {
  it("未選択のときは追加ボタンが無効で「色とサイズを選択してください」", () => {
    renderPanel();
    for (const b of addButtons()) expect(b).toBeDisabled();
    expect(screen.getByTestId("stock-status")).toHaveTextContent("色とサイズを選択してください");
  });

  it("in_stock=false の組合せ（黒 / M）を選ぶとボタン disabled と「在庫切れ」表示", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /^色 黒/ }));
    fireEvent.click(screen.getByRole("button", { name: /^サイズ M/ }));

    expect(screen.getByTestId("stock-status")).toHaveTextContent("在庫切れ");
    for (const b of addButtons()) {
      expect(b).toBeDisabled();
      expect(b).toHaveTextContent("在庫切れ");
    }
    expect(screen.getByRole("button", { name: /^色 黒/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^サイズ M/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("in_stock=true の組合せ（白 / M）に戻すとボタンが有効になり「在庫あり」", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /^色 黒/ }));
    fireEvent.click(screen.getByRole("button", { name: /^サイズ M/ }));
    expect(addButtons()[0]).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /^色 白/ }));
    expect(screen.getByTestId("stock-status")).toHaveTextContent("在庫あり");
    for (const b of addButtons()) {
      expect(b).toBeEnabled();
      expect(b).toHaveTextContent("カートに入れる");
    }
  });

  it("UT-WEB-07: 固定バーの表示内容（色/サイズ/数量/価格）が選択に追従する", () => {
    renderPanel();
    const bar = screen.getByTestId("sticky-bar");
    expect(bar).toHaveTextContent("色未選択 / サイズ未選択 / 1");
    expect(bar).toHaveTextContent("¥1,990");

    fireEvent.click(screen.getByRole("button", { name: /^色 白/ }));
    fireEvent.click(screen.getByRole("button", { name: /^サイズ S/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "数量" }), { target: { value: "3" } });

    expect(bar).toHaveTextContent("白 / S / 3");
    expect(bar).toHaveTextContent("¥5,970");
  });

  it("数量セレクトは 1〜10 の 10 択", () => {
    renderPanel();
    const select = screen.getByRole("combobox", { name: "数量" });
    const options = Array.from(select.querySelectorAll("option")).map((o) => o.value);
    expect(options).toEqual(["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]);
  });
});
