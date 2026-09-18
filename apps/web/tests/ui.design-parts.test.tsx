import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Breadcrumb from "@/components/Breadcrumb";
import Button, { buttonClass } from "@/components/Button";
import { SelectField, TextField } from "@/components/Form";

// デザイン基準 v1（docs/03_設計仕様書/付録_デザイン基準_v1.md 3 章）の共通部品。見た目のクラスと a11y 属性を確認する
describe("Button（基準 3 章）", () => {
  it("primary・lg 既定でピル形・52px 高（h-13）のクラスを持つ", () => {
    render(<Button>カートに入れる</Button>);
    const b = screen.getByRole("button", { name: "カートに入れる" });
    expect(b).toHaveAttribute("type", "button");
    expect(b.className).toContain("rounded-pill");
    expect(b.className).toContain("h-13");
    expect(b.className).toContain("bg-primary");
    expect(b).toBeEnabled();
  });

  it("busy 中はラベルが処理中表示に変わり、無効化＋aria-busy=true", () => {
    const onClick = vi.fn();
    render(
      <Button busy busyLabel="追加中…" onClick={onClick}>
        カートに入れる
      </Button>,
    );
    const b = screen.getByRole("button");
    expect(b).toHaveTextContent("追加中…");
    expect(b).toBeDisabled();
    expect(b).toHaveAttribute("aria-busy", "true");
    fireEvent.click(b);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("buttonClass は variant・size・full を反映する（Link 用）", () => {
    const cls = buttonClass({ variant: "secondary", size: "md", full: true });
    expect(cls).toContain("border-fg");
    expect(cls).toContain("h-11");
    expect(cls).toContain("w-full");
    expect(buttonClass({ variant: "danger" })).toContain("bg-danger");
    expect(buttonClass({ variant: "ghost" })).toContain("hover:underline");
  });
});

describe("Form（基準 3 章 入力欄・セレクト・エラー表示）", () => {
  it("ラベル・（必須）テキスト・44px 高の入力欄", () => {
    render(<TextField id="name" label="氏名" required placeholder="山田 花子" />);
    const input = screen.getByLabelText(/氏名/);
    expect(input).toHaveAttribute("id", "name");
    expect(input).toHaveAttribute("aria-required", "true");
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(input.className).toContain("h-11");
    expect(screen.getByText("（必須）")).toBeInTheDocument();
  });

  it("error を渡すと role=alert の赤文字が出て、aria-invalid / aria-describedby で結ばれる", () => {
    render(<TextField id="tel" label="電話番号" error="電話番号を入力してください" hint="ハイフンなし" />);
    const input = screen.getByLabelText("電話番号");
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("電話番号を入力してください");
    expect(alert).toHaveAttribute("id", "tel-error");
    expect(alert.className).toContain("text-danger");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", "tel-hint tel-error");
  });

  it("SelectField も同じラベル・エラー構造", () => {
    render(
      <SelectField id="pref" label="都道府県" required error="選択してください">
        <option value="">選択</option>
        <option value="13">東京都</option>
      </SelectField>,
    );
    const select = screen.getByRole("combobox", { name: /都道府県/ });
    expect(select).toHaveAttribute("aria-invalid", "true");
    expect(select).toHaveAttribute("aria-describedby", "pref-error");
    expect(screen.getByRole("alert")).toHaveTextContent("選択してください");
  });
});

describe("Breadcrumb（基準 3 章 パンくず）", () => {
  it("nav[aria-label=パンくず]、途中はリンク、最後は aria-current=page のテキスト", () => {
    render(<Breadcrumb items={[{ label: "ホーム", href: "/" }, { label: "商品一覧", href: "/products" }, { label: "ライトジャケット" }]} />);
    expect(screen.getByRole("navigation", { name: "パンくず" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ホーム" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "商品一覧" })).toHaveAttribute("href", "/products");
    const current = screen.getByText("ライトジャケット");
    expect(current).toHaveAttribute("aria-current", "page");
    expect(current.tagName).toBe("SPAN");
  });
});
