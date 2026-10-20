import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AdminOrderDetail from "@/components/admin/AdminOrderDetail";
import { ToastProvider } from "@/components/Toast";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";
import { makeAdminOrder } from "./helpers/admin";

// テスト設計書 UT-WEB-47（注文詳細。DS-SCR-015-4）・ST-SEC-87（XSS）・ST-SEC-88（受け取りコード・電話）の画面側
const replace = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace, refresh, prefetch: vi.fn(), back: vi.fn() }),
}));

beforeEach(() => {
  setCsrfCookie();
});
afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
  refresh.mockReset();
  clearCookies();
});

function renderDetail(patch = {}) {
  return render(
    <ToastProvider>
      <AdminOrderDetail order={makeAdminOrder(patch)} />
    </ToastProvider>,
  );
}

const SHIP = { status: "shipped", label: "出荷済（配送中）", accepts_tracking_number: true };

describe("UT-WEB-47 注文詳細", () => {
  it("次の操作のボタンは available_transitions の件数だけ描画する（1 件）。追跡番号の欄は出ない", () => {
    renderDetail();
    const group = screen.getByRole("group", { name: "次の操作" });
    expect(within(group).getAllByRole("button")).toHaveLength(1);
    expect(within(group).getByRole("button", { name: "出荷準備中にする" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/追跡番号/)).toBeNull();
  });

  it("0 件の状態は「画面で更新できる操作はありません」だけでボタンがない", () => {
    renderDetail({ status: "delivered", status_label: "配達完了", available_transitions: [] });
    expect(screen.getByTestId("admin-no-transitions")).toHaveTextContent("この状態から画面で更新できる操作はありません");
    expect(within(screen.getByRole("group", { name: "次の操作" })).queryAllByRole("button")).toHaveLength(0);
  });

  it("更新先が shipped で accepts_tracking_number が真のときだけ追跡番号の欄（任意）を出す。偽なら出さない", () => {
    const { unmount } = renderDetail({ status: "preparing", status_label: "出荷準備中", available_transitions: [SHIP] });
    expect(screen.getByLabelText(/追跡番号（任意）/)).toBeInTheDocument();
    unmount();
    renderDetail({
      status: "preparing",
      status_label: "店舗へ準備中",
      receive_method: "store",
      available_transitions: [{ status: "shipped", label: "店舗に到着（受け取り可能）", accepts_tracking_number: false }],
    });
    expect(screen.queryByLabelText(/追跡番号/)).toBeNull();
  });

  it("氏名に <script> を入れても文字列として表示され、HTML として解釈されない", () => {
    const evil = "<script>alert(1)</script>";
    const { container } = renderDetail({
      customer: { type: "guest", name: evil, email_masked: "e***@example.com", phone_masked: "*******5678", postal_code: "0000001", address: `"><img src=x onerror=alert(1)>` },
    });
    expect(screen.getByTestId("admin-customer-name")).toHaveTextContent(evil);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.innerHTML).not.toContain("<script>");
  });

  it("受け取りコードの要素が無い（API が余計に返しても描画しない）。電話は末尾 4 桁以外が *、メールはマスク", () => {
    const order = { ...makeAdminOrder(), pickup_code: "ABCD2345", member_id: 99 } as ReturnType<typeof makeAdminOrder>;
    const { container } = render(
      <ToastProvider>
        <AdminOrderDetail order={order} />
      </ToastProvider>,
    );
    expect(container.textContent).not.toContain("ABCD2345");
    expect(container.textContent).not.toContain("ABCD-2345");
    expect(container.textContent).not.toMatch(/受け取りコード/);
    expect(screen.getByTestId("admin-customer-phone")).toHaveTextContent("*******5678");
    expect(screen.getByTestId("admin-customer-email")).toHaveTextContent("d***@example.com");
  });

  it("配送は郵便番号と住所を出し、店舗受け取りは店舗名と住所を出す（郵便番号は出さない）", () => {
    const { unmount } = renderDetail();
    expect(screen.getByText("0000001")).toBeInTheDocument();
    expect(screen.getByText("東京都千代田区デモ町1-2-3")).toBeInTheDocument();
    unmount();
    const { container } = renderDetail({
      receive_method: "store",
      store: { name: "デモ店 東京", prefecture: "東京都", address: "千代田区デモ町1-2-3 デモビル1階" },
      customer: { type: "member", name: "デモ 一郎", email_masked: "d***@example.com", phone_masked: "*******5678" },
    });
    expect(screen.getByText("デモ店 東京")).toBeInTheDocument();
    expect(container.textContent).toContain("東京都 千代田区デモ町1-2-3 デモビル1階");
    expect(container.textContent).not.toContain("お届け先");
  });

  it("明細（商品名・色・サイズ・単価 × 数量）と金額（小計・送料・値引き・合計・うち消費税）を出す", () => {
    renderDetail();
    const items = screen.getAllByTestId("admin-order-item");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("スムースコットンT");
    expect(items[0]).toHaveTextContent("黒 / M");
    expect(items[0]).toHaveTextContent("¥1,990 × 2");
    expect(screen.getByText("うち消費税").nextSibling).toHaveTextContent("¥411");
    expect(screen.getByText("合計").nextSibling).toHaveTextContent("¥4,530");
  });

  it("押すと確認ダイアログを経る: キャンセルでは送らない。OK で PATCH し、状態の表示と次の操作を応答で更新する", async () => {
    const { calls, fn } = mockFetch(() =>
      jsonResponse(200, {
        order_number: "GU-261024-ABCDEFGH",
        status: "preparing",
        status_label: "出荷準備中",
        tracking_number: null,
        available_transitions: [SHIP],
      }),
    );
    renderDetail();
    fireEvent.click(screen.getByTestId("admin-transition-preparing"));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("状態を『出荷準備中』に更新します。元には戻せません");
    fireEvent.click(within(dialog).getByRole("button", { name: "キャンセル" }));
    expect(fn).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("admin-transition-preparing"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "更新する" }));
    await waitFor(() => expect(screen.getByTestId("admin-status-label")).toHaveTextContent("出荷準備中"));
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/admin/api/orders/GU-261024-ABCDEFGH/status");
    expect(calls[0].method).toBe("PATCH");
    expect(calls[0].body).toEqual({ status: "preparing" }); // expected_* は使わない（DS-DEC-113）
    expect(screen.getByTestId("toast")).toHaveTextContent("状態を『出荷準備中』に更新しました");
    expect(refresh).toHaveBeenCalled();
    expect(screen.getByTestId("admin-transition-shipped")).toBeInTheDocument();
    expect(screen.getByLabelText(/追跡番号/)).toBeInTheDocument();
  });

  it("追跡番号つきの出荷: tracking_number を同じ本文で送る。空なら送らない", async () => {
    const { calls } = mockFetch((_u, init) => {
      const b = JSON.parse(init.body as string) as { tracking_number?: string };
      return jsonResponse(200, {
        order_number: "GU-261024-ABCDEFGH",
        status: "shipped",
        status_label: "出荷済（配送中）",
        tracking_number: b.tracking_number ?? null,
        available_transitions: [{ status: "delivered", label: "配達完了", accepts_tracking_number: false }],
      });
    });
    renderDetail({ status: "preparing", status_label: "出荷準備中", available_transitions: [SHIP] });
    fireEvent.change(screen.getByLabelText(/追跡番号/), { target: { value: " AB-123456 " } });
    fireEvent.click(screen.getByTestId("admin-transition-shipped"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "更新する" }));
    await waitFor(() => expect(screen.getByTestId("admin-status-label")).toHaveTextContent("出荷済（配送中）"));
    expect(calls[0].body).toEqual({ status: "shipped", tracking_number: "AB-123456" });
    expect(screen.getByTestId("admin-status-tracking")).toHaveTextContent("AB-123456");
  });

  it("追跡番号なしの出荷は tracking_number を送らない", async () => {
    const { calls } = mockFetch(() =>
      jsonResponse(200, { order_number: "GU-261024-ABCDEFGH", status: "shipped", status_label: "出荷済（配送中）", tracking_number: null, available_transitions: [] }),
    );
    renderDetail({ status: "preparing", status_label: "出荷準備中", available_transitions: [SHIP] });
    fireEvent.click(screen.getByTestId("admin-transition-shipped"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "更新する" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toEqual({ status: "shipped" });
  });

  it.each([["あいう"], ["AB 123"], ["AB_123"], ["A".repeat(51)]])("追跡番号 %j は形が違うので確認ダイアログも出さず送らない", (bad) => {
    const { fn } = mockFetch(() => jsonResponse(200, {}));
    renderDetail({ status: "preparing", status_label: "出荷準備中", available_transitions: [SHIP] });
    fireEvent.change(screen.getByLabelText(/追跡番号/), { target: { value: bad } });
    fireEvent.click(screen.getByTestId("admin-transition-shipped"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fn).not.toHaveBeenCalled();
    expect(screen.getByText(/半角の英数字とハイフン/, { selector: "[role=alert]" })).toBeInTheDocument();
  });

  it("409 invalid_transition: 「この注文の状態はすでに変わっています。画面を更新しました」を出して再読み込み(refresh)", async () => {
    mockFetch(() => jsonResponse(409, { code: "invalid_transition", from: "shipped", to: "preparing" }));
    renderDetail();
    fireEvent.click(screen.getByTestId("admin-transition-preparing"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "更新する" }));
    await waitFor(() => expect(screen.getByTestId("toast")).toHaveTextContent("この注文の状態はすでに変わっています。画面を更新しました"));
    expect(screen.getByTestId("toast")).toHaveAttribute("data-kind", "error");
    expect(refresh).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("422（追跡番号を付けられない注文）は枠の中の role=alert に文言", async () => {
    mockFetch(() => jsonResponse(422, { code: "unsupported_value", field: "tracking_number" }));
    renderDetail({ status: "preparing", status_label: "出荷準備中", available_transitions: [SHIP] });
    fireEvent.click(screen.getByTestId("admin-transition-shipped"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "更新する" }));
    await waitFor(() => expect(screen.getByTestId("admin-status-error")).toHaveTextContent("追跡番号を付けられない注文です"));
  });

  it("401 は /admin/login?expired=1 へ移す", async () => {
    mockFetch(() => jsonResponse(401, { code: "unauthorized" }));
    renderDetail();
    fireEvent.click(screen.getByTestId("admin-transition-preparing"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "更新する" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin/login?expired=1"));
  });
});
