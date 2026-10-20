import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AdminPager from "@/components/admin/AdminPager";

// テスト設計書 UT-WEB-54（ページ送り。AdminPager）

const base = { basePath: "/admin/orders", linkParams: { status: "shipped", email: "a@example.com" }, perPage: 20 };

function hrefs() {
  return Array.from(screen.getByRole("navigation", { name: "ページ送り" }).querySelectorAll("a")).map((a) => a.getAttribute("href"));
}

describe("UT-WEB-54 ページ送り", () => {
  it("総件数 0 は「該当なし」で、ページ送りを出さない", () => {
    render(<AdminPager {...base} page={1} total={0} hasMore={false} />);
    expect(screen.getByTestId("admin-pager-count")).toHaveTextContent("該当なし");
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("1 ページだけなら件数だけでページ送りを出さない", () => {
    render(<AdminPager {...base} page={1} total={20} hasMore={false} />);
    expect(screen.getByTestId("admin-pager-count")).toHaveTextContent("全 20 件");
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("先頭: 「前へ」なし、「次へ」あり。1 ページ目のリンクには page を付けず、検索条件を保つ", () => {
    render(<AdminPager {...base} page={1} total={45} hasMore />);
    expect(screen.queryByText(/前へ/)).toBeNull();
    expect(screen.getByText(/次へ/)).toBeInTheDocument();
    expect(hrefs()).toEqual([
      "/admin/orders?status=shipped&email=a%40example.com&page=2",
      "/admin/orders?status=shipped&email=a%40example.com&page=3",
      "/admin/orders?status=shipped&email=a%40example.com&page=2",
    ]);
    expect(screen.getByText("1")).toHaveAttribute("aria-current", "page");
  });

  it("中間: 前へ・次への両方。前へは page-1(2→1 は page を付けない)", () => {
    render(<AdminPager {...base} page={2} total={65} hasMore />);
    const links = hrefs();
    expect(links[0]).toBe("/admin/orders?status=shipped&email=a%40example.com"); // 前へ（1 ページ目）
    expect(screen.getByText(/前へ/)).toBeInTheDocument();
    expect(screen.getByText(/次へ/)).toBeInTheDocument();
    expect(links.at(-1)).toBe("/admin/orders?status=shipped&email=a%40example.com&page=3");
  });

  it("最終: 「次へ」なし(has_more が偽)、「前へ」あり", () => {
    render(<AdminPager {...base} page={3} total={45} hasMore={false} />);
    expect(screen.getByText(/前へ/)).toBeInTheDocument();
    expect(screen.queryByText(/次へ/)).toBeNull();
    expect(screen.getByText("3")).toHaveAttribute("aria-current", "page");
  });

  it("リンクの page は 1 以上の整数。現在のページが不正(0・小数)でも page=0 のリンクを出さない", () => {
    render(<AdminPager {...base} page={0} total={45} hasMore />);
    for (const h of hrefs()) {
      const p = new URL(h!, "http://x").searchParams.get("page");
      if (p !== null) expect(Number.isInteger(Number(p)) && Number(p) >= 1).toBe(true);
    }
  });

  it("ページ番号は現在の前後 2 ページずつの窓", () => {
    render(<AdminPager {...base} page={10} total={400} hasMore />);
    const nav = screen.getByRole("navigation", { name: "ページ送り" });
    const numbers = Array.from(nav.querySelectorAll("a, span[aria-current]")).map((e) => e.textContent).filter((t) => /^\d+$/.test(t ?? ""));
    expect(numbers).toEqual(["8", "9", "10", "11", "12"]);
  });
});
