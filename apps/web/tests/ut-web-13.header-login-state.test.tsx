import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Header from "@/components/Header";

// テスト設計書 UT-WEB-13（Header のログイン状態。DS-SCR 共通・DS-DEC-86）。設計仕様書 6.2
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

describe("UT-WEB-13 Header のログイン状態", () => {
  it("signedIn=false（既定）: aria-label=ログイン・リンク先 /login", () => {
    render(<Header cartCount={0} signedIn={false} />);
    const link = screen.getByRole("link", { name: "ログイン" });
    expect(link).toHaveAttribute("href", "/login");
    expect(screen.queryByRole("link", { name: "マイページ" })).not.toBeInTheDocument();
  });

  it("signedIn を渡さないときも未ログインの表示", () => {
    render(<Header cartCount={0} />);
    expect(screen.getByRole("link", { name: "ログイン" })).toHaveAttribute("href", "/login");
  });

  it("signedIn=true: aria-label=マイページ・リンク先 /mypage", () => {
    render(<Header cartCount={2} signedIn />);
    const link = screen.getByRole("link", { name: "マイページ" });
    expect(link).toHaveAttribute("href", "/mypage");
    expect(screen.queryByRole("link", { name: "ログイン" })).not.toBeInTheDocument();
  });

  it("会員アイコンは 44px 以上（size-11）のタッチターゲット", () => {
    render(<Header cartCount={0} signedIn />);
    expect(screen.getByRole("link", { name: "マイページ" }).className).toMatch(/\bsize-11\b/);
  });
});
