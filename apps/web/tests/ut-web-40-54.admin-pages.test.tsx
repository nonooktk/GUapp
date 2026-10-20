import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// 管理ページ(Server Component)の組み立て: レイアウトのシェル、ログイン画面のリダイレクト、検索条件の検査、404。
// 設計仕様書 P2 追補c 6.1〜6.6。lib/server/admin はモックし、ページが何を呼ぶか・何を描くかを確かめる

class RedirectSignal extends Error {
  constructor(readonly to: string) {
    super(`redirect:${to}`);
  }
}
class NotFoundSignal extends Error {}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new RedirectSignal(to);
  },
  notFound: () => {
    throw new NotFoundSignal();
  },
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/products",
}));

const admin = {
  getAdminOrNull: vi.fn(),
  requireAdmin: vi.fn(async () => undefined),
  loadAdminProducts: vi.fn(),
  loadAdminProduct: vi.fn(),
  loadAdminOrders: vi.fn(),
  loadAdminOrder: vi.fn(),
  loadAdminSettings: vi.fn(),
};
vi.mock("@/lib/server/admin", () => admin);

beforeEach(() => {
  for (const f of Object.values(admin)) f.mockReset();
  admin.requireAdmin.mockResolvedValue(undefined);
});

const sp = (v: Record<string, string | string[] | undefined>) => ({ searchParams: Promise.resolve(v) });
const params = <T extends Record<string, string>>(v: T) => ({ params: Promise.resolve(v) });
const page = <T,>(mod: { default: unknown }) => mod.default as (props: T) => Promise<React.ReactElement>;

describe("/admin のレイアウト", () => {
  it("管理者を確認できたらシェル(login_id・メニュー・ログアウト)を付ける", async () => {
    admin.getAdminOrNull.mockResolvedValue({ login_id: "demo-staff", role: "staff" });
    const Layout = page<{ children: React.ReactNode }>(await import("@/app/admin/layout"));
    render(await Layout({ children: <p>本文</p> }));
    expect(screen.getByTestId("admin-staff-id")).toHaveTextContent("demo-staff");
    expect(screen.getByRole("navigation", { name: "管理メニュー" })).toBeInTheDocument();
    expect(screen.getByText("本文")).toBeInTheDocument();
  });

  it("確認できない(未ログイン・失効・会員のセッション)ときはシェルを付けず本文だけ(ログイン画面用)。redirect はしない", async () => {
    admin.getAdminOrNull.mockResolvedValue(null);
    const Layout = page<{ children: React.ReactNode }>(await import("@/app/admin/layout"));
    render(await Layout({ children: <p>本文</p> }));
    expect(screen.queryByRole("navigation", { name: "管理メニュー" })).toBeNull();
    expect(screen.queryByTestId("admin-logout")).toBeNull();
    expect(screen.getByRole("main")).toHaveTextContent("本文");
  });

  it("全ページ検索エンジンに載せない metadata", async () => {
    const { metadata } = await import("@/app/admin/layout");
    expect(metadata.robots).toEqual({ index: false, follow: false });
  });
});

describe("/admin と /admin/login", () => {
  it("/admin は /admin/products へ redirect", async () => {
    const Index = (await import("@/app/admin/page")).default as () => never;
    expect(() => Index()).toThrowError(expect.objectContaining({ to: "/admin/products" }));
  });

  it("ログイン画面: 管理者としてログイン済みなら /admin/products へ。Cookie があるだけでは移さない(getAdminOrNull が null ならフォーム)", async () => {
    const Login = page<ReturnType<typeof sp>>(await import("@/app/admin/login/page"));
    admin.getAdminOrNull.mockResolvedValue({ login_id: "demo-staff", role: "staff" });
    await expect(Login(sp({}))).rejects.toMatchObject({ to: "/admin/products" });
    admin.getAdminOrNull.mockResolvedValue(null);
    render(await Login(sp({})));
    expect(screen.getByRole("form", { name: "管理者ログイン" })).toBeInTheDocument();
    expect(screen.queryByTestId("admin-expired")).toBeNull();
  });

  it("?next= は受けない(ログイン済みでも常に /admin/products)。?expired=1 で案内を出す", async () => {
    const Login = page<ReturnType<typeof sp>>(await import("@/app/admin/login/page"));
    admin.getAdminOrNull.mockResolvedValue({ login_id: "demo-staff", role: "staff" });
    await expect(Login(sp({ next: "//evil.example" }))).rejects.toMatchObject({ to: "/admin/products" });
    admin.getAdminOrNull.mockResolvedValue(null);
    render(await Login(sp({ expired: "1", next: "//evil.example" })));
    expect(screen.getByTestId("admin-expired")).toBeInTheDocument();
  });
});

describe("商品一覧ページ", () => {
  it("検索条件を検査して、検査済みの値だけを FastAPI に渡す", async () => {
    admin.loadAdminProducts.mockResolvedValue({ kind: "ok", data: { items: [], page: 1, per_page: 20, total: 0, has_more: false } });
    const Products = page<ReturnType<typeof sp>>(await import("@/app/admin/products/page"));
    render(await Products(sp({ q: "あ".repeat(80), visibility: "zzz", stock: ["out", "x"], page: "0", sort: "price" })));
    const query = new URLSearchParams(admin.loadAdminProducts.mock.calls[0][0] as string);
    expect(Array.from(query.get("q")!)).toHaveLength(50);
    expect(query.get("stock")).toBe("out");
    expect(query.has("visibility")).toBe(false);
    expect(query.get("page")).toBe("1");
    expect(query.has("sort")).toBe(false);
    expect(screen.getByTestId("admin-products-empty")).toBeInTheDocument();
    expect(screen.getByTestId("admin-pager-count")).toHaveTextContent("該当なし");
  });

  it("取得に失敗したら LoadError(検索フォームは出す)", async () => {
    admin.loadAdminProducts.mockResolvedValue({ kind: "error", status: 500, body: { code: "internal_error" } });
    const Products = page<ReturnType<typeof sp>>(await import("@/app/admin/products/page"));
    render(await Products(sp({})));
    expect(screen.getByRole("alert")).toHaveTextContent("商品を読み込めませんでした");
    expect(screen.getByRole("form", { name: "商品の検索" })).toBeInTheDocument();
  });
});

describe("商品の編集ページ", () => {
  it("形が違う ID は FastAPI を呼ばずに 404。存在しなければ 404。取得に失敗したら LoadError", async () => {
    const Product = page<ReturnType<typeof params>>(await import("@/app/admin/products/[productId]/page"));
    for (const bad of ["abc", "0", "01", "1".repeat(20), "-1"]) {
      await expect(Product(params({ productId: bad }))).rejects.toBeInstanceOf(NotFoundSignal);
    }
    expect(admin.loadAdminProduct).not.toHaveBeenCalled();
    admin.loadAdminProduct.mockResolvedValueOnce({ kind: "not_found" });
    await expect(Product(params({ productId: "99" }))).rejects.toBeInstanceOf(NotFoundSignal);
    admin.loadAdminProduct.mockResolvedValueOnce({ kind: "error", status: 500, body: null });
    render(await Product(params({ productId: "12" })));
    expect(screen.getByRole("alert")).toHaveTextContent("商品を読み込めませんでした");
    expect(admin.loadAdminProduct).toHaveBeenLastCalledWith("12");
  });
});

describe("注文一覧ページ", () => {
  const empty = { kind: "ok", data: { items: [], page: 1, per_page: 20, total: 0, has_more: false } };

  it("検索条件が正しければ検査済みのクエリで FastAPI を呼ぶ", async () => {
    admin.loadAdminOrders.mockResolvedValue(empty);
    const Orders = page<ReturnType<typeof sp>>(await import("@/app/admin/orders/page"));
    render(await Orders(sp({ status: "shipped", from: "2026-10-01", to: "2026-10-31", email: "A@Example.com" })));
    const q = new URLSearchParams(admin.loadAdminOrders.mock.calls[0][0] as string);
    expect(Object.fromEntries(q)).toEqual({ status: "shipped", from: "2026-10-01", to: "2026-10-31", email: "a@example.com", page: "1" });
    expect(admin.requireAdmin).not.toHaveBeenCalled();
  });

  it("日付・注文番号・メールの形が違えば FastAPI に一覧を取りに行かず、画面にエラー。ただし管理者の確認(未ログインなら redirect)は行う", async () => {
    const Orders = page<ReturnType<typeof sp>>(await import("@/app/admin/orders/page"));
    render(await Orders(sp({ from: "2026-02-30", order_number: "' OR 1=1 --" })));
    expect(admin.loadAdminOrders).not.toHaveBeenCalled();
    expect(admin.requireAdmin).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole("alert").length).toBeGreaterThanOrEqual(2);

    admin.requireAdmin.mockRejectedValueOnce(new RedirectSignal("/admin/login"));
    await expect(Orders(sp({ from: "bad" }))).rejects.toMatchObject({ to: "/admin/login" });
  });

  it("FastAPI が 422(期間が 366 日超)を返したら、一覧を出さず文言をフォームに出す", async () => {
    admin.loadAdminOrders.mockResolvedValue({ kind: "error", status: 422, body: { code: "limit_exceeded", field: "to", limit: 366 } });
    const Orders = page<ReturnType<typeof sp>>(await import("@/app/admin/orders/page"));
    render(await Orders(sp({ from: "2020-01-01", to: "2026-01-01" })));
    expect(screen.getByTestId("admin-orders-api-error")).toBeInTheDocument();
    expect(screen.queryByTestId("admin-order-row")).toBeNull();
  });

  it("500 は LoadError", async () => {
    admin.loadAdminOrders.mockResolvedValue({ kind: "error", status: 500, body: null });
    const Orders = page<ReturnType<typeof sp>>(await import("@/app/admin/orders/page"));
    render(await Orders(sp({})));
    expect(screen.getByText(/注文を読み込めませんでした/)).toBeInTheDocument();
  });
});

describe("注文詳細・設定のページ", () => {
  it("注文が無い(形が違う番号を含む)なら 404。取得に失敗したら LoadError", async () => {
    const Order = page<ReturnType<typeof params>>(await import("@/app/admin/orders/[orderNumber]/page"));
    admin.loadAdminOrder.mockResolvedValueOnce({ kind: "not_found" });
    await expect(Order(params({ orderNumber: "x" }))).rejects.toBeInstanceOf(NotFoundSignal);
    admin.loadAdminOrder.mockResolvedValueOnce({ kind: "error", status: 503, body: null });
    render(await Order(params({ orderNumber: "GU-261024-ABCDEFGH" })));
    expect(screen.getByRole("alert")).toHaveTextContent("注文を読み込めませんでした");
  });

  it("設定: 取得に失敗したら LoadError。成功すれば 3 項目の入力欄を出す", async () => {
    const Settings = (await import("@/app/admin/settings/page")).default as () => Promise<React.ReactElement>;
    admin.loadAdminSettings.mockResolvedValueOnce({ kind: "error", status: 500, body: null });
    const { unmount } = render(await Settings());
    expect(screen.getByRole("alert")).toHaveTextContent("設定を読み込めませんでした");
    unmount();
    const { ADMIN_SETTING_ITEMS } = await import("./helpers/admin");
    admin.loadAdminSettings.mockResolvedValueOnce({ kind: "ok", data: { items: ADMIN_SETTING_ITEMS } });
    const { ToastProvider } = await import("@/components/Toast");
    render(<ToastProvider>{await Settings()}</ToastProvider>);
    expect(screen.getAllByRole("textbox")).toHaveLength(3);
  });
});
