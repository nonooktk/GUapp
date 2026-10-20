import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CheckoutForm from "@/components/CheckoutForm";
import { ToastProvider } from "@/components/Toast";
import { CHECKOUT_KEY, saveCheckoutSession, type CheckoutSession } from "@/lib/checkout-session";
import { DEMO_CHECKOUT_FORM } from "@/lib/demo-defaults";
import type { PrepareResponse, StoreSummary } from "@/lib/types";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";

// テスト設計書 UT-WEB-20（注文手続きの受け取り方法。DS-SCR-005）。設計仕様書 6.7・DS-PRC-021a・014-3・AT-15
const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

const STORES: StoreSummary[] = [
  { code: "demo-tokyo", name: "デモ店 東京", prefecture: "東京都", address: "千代田区デモ町1-2-3 デモビル1階" },
  { code: "demo-osaka", name: "デモ店 大阪", prefecture: "大阪府", address: "大阪市デモ町4-5-6" },
];

const prepareOut = (method: "delivery" | "store"): PrepareResponse => ({
  receive_method: method,
  idempotency_key: "idemKey_-0123456789abcdefghijklmnopqrstuvwx", // gitleaks:allow // pragma: allowlist secret
  items: [],
  subtotal: 3980,
  shipping_fee: method === "store" ? 0 : 550,
  total: method === "store" ? 3980 : 4530,
  tax_included: 361,
  tax_rate: "0.10",
  free_shipping_threshold: 4990,
});

beforeEach(() => {
  setCsrfCookie();
  push.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  clearCookies();
});

function renderForm(props: Parameters<typeof CheckoutForm>[0] = {}) {
  return render(
    <ToastProvider>
      <CheckoutForm {...props} />
    </ToastProvider>,
  );
}
const chooseStoreMethod = () => fireEvent.click(screen.getByRole("radio", { name: /店舗受け取り/ }));
const chooseDeliveryMethod = () => fireEvent.click(screen.getByRole("radio", { name: /^配送/ }));
const submit = () => fireEvent.click(screen.getByTestId("to-confirm"));
const savedSession = () => JSON.parse(window.sessionStorage.getItem(CHECKOUT_KEY) ?? "null") as CheckoutSession;

describe("UT-WEB-20 受け取り方法の切り替え", () => {
  it("既定は配送。店舗を選ぶと住所の欄（郵便番号・都道府県・市区町村・番地・建物）が消え、受け取り店舗のセレクトが出る", () => {
    renderForm({ stores: STORES });
    expect(screen.getByLabelText(/^郵便番号/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^受け取り店舗/)).not.toBeInTheDocument();

    chooseStoreMethod();
    for (const label of [/^郵便番号/, /^都道府県/, /^市区町村/, /^番地/, /^建物名/]) {
      expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
    }
    expect(screen.getByLabelText(/^氏名/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^電話番号/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^メールアドレス/)).toBeInTheDocument();
    const select = screen.getByLabelText(/^受け取り店舗/);
    expect(select).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /デモ店 東京（東京都 千代田区デモ町1-2-3 デモビル1階）/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "受け取る方" })).toBeInTheDocument();
  });

  it("店舗未選択で「確認画面へ」を押すとエラー（prepare は呼ばない）", () => {
    const { fn } = mockFetch(() => jsonResponse(200, prepareOut("store")));
    renderForm({ stores: STORES });
    chooseStoreMethod();
    submit();
    expect(fn).not.toHaveBeenCalled();
    expect(screen.getByText("受け取り店舗を選択してください")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("店舗を選んで確認へ: prepare に receive_method=store を渡し、保存値に郵便番号・住所を含めず、店舗コードと店舗情報を保存する", async () => {
    const { calls } = mockFetch(() => jsonResponse(200, prepareOut("store")));
    renderForm({ stores: STORES });
    chooseStoreMethod();
    fireEvent.change(screen.getByLabelText(/^受け取り店舗/), { target: { value: "demo-tokyo" } });
    submit();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/checkout/confirm"));

    expect(calls[0].url).toBe("/api/checkout/prepare");
    expect(calls[0].body).toEqual({ receive_method: "store" });
    const s = savedSession();
    expect(s.receive_method).toBe("store");
    expect(s.store_code).toBe("demo-tokyo");
    expect(s.store?.name).toBe("デモ店 東京");
    expect(s.prepare?.shipping_fee).toBe(0);
    expect(s.form.name).toBe(DEMO_CHECKOUT_FORM.name);
    expect(s.form.postal).toBe("");
    expect(s.form.prefecture).toBe("");
    expect(s.form.city).toBe("");
    expect(s.form.street).toBe("");
    expect(s.form.building).toBe("");
  });

  it("店舗受け取りでは住所が不正でも（欄が無いので）検査しない。氏名が空なら止まる", async () => {
    const { fn } = mockFetch(() => jsonResponse(200, prepareOut("store")));
    renderForm({ stores: STORES });
    fireEvent.change(screen.getByLabelText(/^市区町村/), { target: { value: "" } }); // 配送のまま空にして
    chooseStoreMethod(); // 店舗へ切り替えると市区町村は検査対象外
    fireEvent.change(screen.getByLabelText(/^受け取り店舗/), { target: { value: "demo-osaka" } });
    fireEvent.change(screen.getByLabelText(/^氏名/), { target: { value: "" } });
    submit();
    expect(fn).not.toHaveBeenCalled();
    expect(screen.getAllByText("入力してください").length).toBeGreaterThan(0);
  });

  it("配送に戻すと入力済みの値が残る。配送の prepare は receive_method=delivery で、保存値は住所を含む", async () => {
    const { calls } = mockFetch(() => jsonResponse(200, prepareOut("delivery")));
    renderForm({ stores: STORES });
    fireEvent.change(screen.getByLabelText(/^市区町村/), { target: { value: "新宿区" } });
    chooseStoreMethod();
    chooseDeliveryMethod();
    expect(screen.getByLabelText(/^市区町村/)).toHaveValue("新宿区");

    submit();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/checkout/confirm"));
    expect(calls[0].body).toEqual({ receive_method: "delivery" });
    const s = savedSession();
    expect(s.receive_method).toBe("delivery");
    expect(s.store_code).toBeUndefined();
    expect(s.form.city).toBe("新宿区");
    expect(s.form.postal).toBe(DEMO_CHECKOUT_FORM.postal);
  });

  it("確認画面から戻ったとき、店舗受け取りの選択と店舗を復元する（住所の欄は配送に戻したときダミー値）", () => {
    saveCheckoutSession({
      form: { ...DEMO_CHECKOUT_FORM, postal: "", prefecture: "", city: "", street: "", building: "" },
      prepare: null,
      receive_method: "store",
      store_code: "demo-osaka",
      store: STORES[1],
    });
    renderForm({ stores: STORES });
    expect(screen.getByRole("radio", { name: /店舗受け取り/ })).toBeChecked();
    expect(screen.getByLabelText(/^受け取り店舗/)).toHaveValue("demo-osaka");
    chooseDeliveryMethod();
    expect(screen.getByLabelText(/^市区町村/)).toHaveValue(DEMO_CHECKOUT_FORM.city);
  });

  it("店舗の取得に失敗した props（null）や空の一覧では店舗受け取りを選べない", () => {
    const { unmount } = renderForm({ stores: null });
    expect(screen.getByRole("radio", { name: /店舗受け取り/ })).toBeDisabled();
    expect(screen.getByTestId("stores-unavailable")).toBeInTheDocument();
    unmount();
    renderForm({ stores: [] });
    expect(screen.getByRole("radio", { name: /店舗受け取り/ })).toBeDisabled();
  });
});

describe("UT-WEB-20 ログイン導線", () => {
  it("未ログイン: 「ログイン」は /login?next=/checkout へのリンク。ゲストのカードも出る", () => {
    renderForm({ stores: STORES });
    expect(screen.getByRole("link", { name: "ログイン" })).toHaveAttribute("href", "/login?next=/checkout");
    expect(screen.getByRole("radio", { name: /ゲストで購入/ })).toBeChecked();
    expect(screen.queryByTestId("member-card")).not.toBeInTheDocument();
  });

  it("ログイン中: 氏名とメールが初期値になり、ゲストのカードは出ない。変更はできる", () => {
    renderForm({ member: { name: "デモ 一郎", email: "demo-member1@example.com" }, stores: STORES });
    expect(screen.getByTestId("member-card")).toHaveTextContent("ログイン中: デモ 一郎 様");
    expect(screen.getByLabelText(/^氏名/)).toHaveValue("デモ 一郎");
    expect(screen.getByLabelText(/^メールアドレス/)).toHaveValue("demo-member1@example.com");
    expect(screen.queryByRole("radio", { name: /ゲストで購入/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "ログイン" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^氏名/), { target: { value: "別名 太郎" } });
    expect(screen.getByLabelText(/^氏名/)).toHaveValue("別名 太郎");
  });

  it("復元値（sessionStorage）があるときは会員情報よりそちらを優先する", () => {
    saveCheckoutSession({ form: { ...DEMO_CHECKOUT_FORM, name: "復元 太郎", email: "restored@example.com" }, prepare: null });
    renderForm({ member: { name: "デモ 一郎", email: "demo-member1@example.com" }, stores: STORES });
    expect(screen.getByLabelText(/^氏名/)).toHaveValue("復元 太郎");
    expect(screen.getByLabelText(/^メールアドレス/)).toHaveValue("restored@example.com");
  });
});
