import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AdminShell from "@/components/admin/AdminShell";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";

// テスト設計書 UT-WEB-41（管理シェル。DS-SCR 6.2）
const replace = vi.fn();
const refresh = vi.fn();
let pathname = "/admin/products";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace, refresh, prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => pathname,
}));

beforeEach(() => {
  setCsrfCookie();
});
afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
  refresh.mockReset();
  clearCookies();
  pathname = "/admin/products";
});

function renderShell(props: Partial<React.ComponentProps<typeof AdminShell>> = {}) {
  return render(
    <AdminShell loginId="demo-staff" {...props}>
      <p>本文</p>
    </AdminShell>,
  );
}

describe("UT-WEB-41 管理シェル", () => {
  it.each([
    ["/admin/products", "商品"],
    ["/admin/orders", "注文"],
    ["/admin/settings", "設定"],
    ["/admin/products/12", "商品"],
    ["/admin/orders/GU-261024-ABCDEFGH", "注文"],
  ])("現在のパス %s では「%s」だけに aria-current=page が付く", (path, current) => {
    pathname = path;
    renderShell();
    const menu = screen.getByRole("navigation", { name: "管理メニュー" });
    const links = Array.from(menu.querySelectorAll("a"));
    expect(links.map((a) => a.textContent)).toEqual(["商品", "注文", "設定"]);
    for (const a of links) {
      if (a.textContent === current) expect(a).toHaveAttribute("aria-current", "page");
      else expect(a).not.toHaveAttribute("aria-current");
    }
  });

  it("右上に login_id とログアウトが出る。「管理」の見出しと本文が出る", () => {
    renderShell();
    expect(screen.getByTestId("admin-staff-id")).toHaveTextContent("demo-staff");
    expect(screen.getByRole("button", { name: "ログアウト" })).toBeInTheDocument();
    expect(screen.getByTestId("admin-title")).toHaveTextContent("管理");
    expect(screen.getByText("本文")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("顧客向けのヘッダー（ホーム・検索・カート・ログイン）・フッター・公開サイトへのリンクが出ない", () => {
    const { container } = renderShell();
    expect(screen.queryByLabelText("GU ホーム")).toBeNull();
    expect(screen.queryByLabelText(/カート/)).toBeNull();
    expect(screen.queryByRole("search")).toBeNull();
    expect(screen.queryByRole("contentinfo")).toBeNull();
    expect(container.querySelector("footer")).toBeNull();
    const hrefs = Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(hrefs.every((h) => h?.startsWith("/admin"))).toBe(true);
  });

  it("設定の画面が無効のときはメニューに「設定」が出ない", () => {
    renderShell({ settingsEnabled: false });
    const menu = screen.getByRole("navigation", { name: "管理メニュー" });
    expect(Array.from(menu.querySelectorAll("a")).map((a) => a.textContent)).toEqual(["商品", "注文"]);
  });

  it("ログアウト: POST /admin/api/auth/logout（CSRF つき）→ /admin/login へ replace と refresh", async () => {
    const { calls } = mockFetch(() => jsonResponse(204, null));
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "ログアウト" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin/login"));
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/admin/api/auth/logout");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].headers.get("X-CSRF-Token")).toBeTruthy();
  });

  it("ログアウトが失敗しても /admin/login へ移す", async () => {
    mockFetch(() => jsonResponse(503, { code: "upstream_unavailable" }));
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "ログアウト" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin/login"));
  });
});
