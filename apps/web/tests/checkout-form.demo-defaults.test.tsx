import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CheckoutForm from "@/components/CheckoutForm";
import { ToastProvider } from "@/components/Toast";
import { saveCheckoutSession } from "@/lib/checkout-session";
import { validateCheckoutForm } from "@/lib/checkout-validation";
import { DEMO_CHECKOUT_FORM, DEMO_NOTICE_BODY, DEMO_NOTICE_TITLE } from "@/lib/demo-defaults";

// デモの個人情報対策（設計仕様書 P2 追補a 9.1 DS-DEC-47）。
// 講義の Azure MySQL・開いた dev サーバーへ、利用者が誤って本物の氏名・住所・電話・メールを
// 入力してしまう事故を防ぐため、注文手続きフォームの初期値をダミー値にし、注意書きを表示する。

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

const RESTORED_FORM = {
  name: "テスト 太郎",
  postal: "100-0001",
  prefecture: "東京都",
  city: "千代田区",
  street: "千代田1-1",
  building: "テストビル 101",
  phone: "090-1234-5678",
  email: "test@example.com",
};

function renderForm() {
  return render(
    <ToastProvider>
      <CheckoutForm />
    </ToastProvider>,
  );
}

describe("CheckoutForm のデモ初期値・注意書き（DS-DEC-47）", () => {
  afterEach(() => {
    window.sessionStorage.clear();
  });

  it("sessionStorage に復元値が無いとき、配送先の各欄にダミー値が入る", () => {
    renderForm();
    expect(screen.getByLabelText(/^氏名/)).toHaveValue(DEMO_CHECKOUT_FORM.name);
    expect(screen.getByLabelText(/^郵便番号/)).toHaveValue(DEMO_CHECKOUT_FORM.postal);
    expect(screen.getByLabelText(/^都道府県/)).toHaveValue(DEMO_CHECKOUT_FORM.prefecture);
    expect(screen.getByLabelText(/^市区町村/)).toHaveValue(DEMO_CHECKOUT_FORM.city);
    expect(screen.getByLabelText(/^番地/)).toHaveValue(DEMO_CHECKOUT_FORM.street);
    expect(screen.getByLabelText(/^建物名/)).toHaveValue(DEMO_CHECKOUT_FORM.building);
    expect(screen.getByLabelText(/^電話番号/)).toHaveValue(DEMO_CHECKOUT_FORM.phone);
    expect(screen.getByLabelText(/^メールアドレス/)).toHaveValue(DEMO_CHECKOUT_FORM.email);
  });

  it("お届け先の近くに注意書きが表示される", () => {
    renderForm();
    const note = screen.getByRole("note", { name: "デモに関する注意" });
    expect(note).toHaveTextContent(DEMO_NOTICE_TITLE);
    expect(note).toHaveTextContent(DEMO_NOTICE_BODY);
  });

  it("sessionStorage に復元値があるときは、ダミー値ではなく復元値を優先する", () => {
    saveCheckoutSession({ form: RESTORED_FORM, prepare: null });
    renderForm();
    expect(screen.getByLabelText(/^氏名/)).toHaveValue(RESTORED_FORM.name);
    expect(screen.getByLabelText(/^郵便番号/)).toHaveValue(RESTORED_FORM.postal);
    expect(screen.getByLabelText(/^都道府県/)).toHaveValue(RESTORED_FORM.prefecture);
    expect(screen.getByLabelText(/^市区町村/)).toHaveValue(RESTORED_FORM.city);
    expect(screen.getByLabelText(/^番地/)).toHaveValue(RESTORED_FORM.street);
    expect(screen.getByLabelText(/^建物名/)).toHaveValue(RESTORED_FORM.building);
    expect(screen.getByLabelText(/^電話番号/)).toHaveValue(RESTORED_FORM.phone);
    expect(screen.getByLabelText(/^メールアドレス/)).toHaveValue(RESTORED_FORM.email);
  });

  it("ダミー値はクライアント側の入力検証（checkout-validation）をそのまま通る", () => {
    expect(validateCheckoutForm(DEMO_CHECKOUT_FORM)).toEqual({});
  });
});
