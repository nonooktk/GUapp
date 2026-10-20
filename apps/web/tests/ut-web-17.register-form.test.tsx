import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RegisterForm from "@/components/RegisterForm";
import { passwordLength } from "@/lib/auth-validation";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";

// テスト設計書 UT-WEB-17（登録フォーム）。設計仕様書 6.3・DS-API-030・DS-DEC-69・71・76・AT-13
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

beforeEach(() => setCsrfCookie());
afterEach(() => {
  vi.unstubAllGlobals();
  clearCookies();
});

const GOOD_PW = "correct-horse-1"; // pragma: allowlist secret

function fill(v: { email?: string; password?: string; name?: string }) {
  if (v.email !== undefined) fireEvent.change(screen.getByLabelText(/^メールアドレス/), { target: { value: v.email } });
  if (v.password !== undefined) fireEvent.change(screen.getByLabelText(/^パスワード/), { target: { value: v.password } });
  if (v.name !== undefined) fireEvent.change(screen.getByLabelText(/^氏名/), { target: { value: v.name } });
}
const submit = () => fireEvent.click(screen.getByTestId("register-submit"));

describe("UT-WEB-17 登録フォーム", () => {
  it("デモの注意書きが常に出る。メール欄の入力例は demo@example.com", () => {
    render(<RegisterForm />);
    expect(screen.getByRole("note", { name: "デモに関する注意" })).toBeInTheDocument();
    expect(screen.getByLabelText(/^メールアドレス/)).toHaveAttribute("placeholder", "demo@example.com");
  });

  it.each([
    ["7 文字", "a".repeat(7), false],
    ["8 文字", "a".repeat(8), true],
    ["128 文字", "a".repeat(128), true],
    ["129 文字", "a".repeat(129), false],
    ["全角 8 文字（NFKC で 8 文字）", "ａｂｃｄｅｆｇｈ", true],
    ["全角 7 文字", "ａｂｃｄｅｆｇ", false],
  ])("パスワード %s の検査", async (_label, pw, ok) => {
    const { fn } = mockFetch(() => jsonResponse(202, { status: "accepted" }));
    render(<RegisterForm />);
    fill({ email: "new@example.com", password: pw, name: "テスト" });
    submit();
    if (ok) {
      await waitFor(() => expect(fn).toHaveBeenCalledTimes(1));
    } else {
      expect(await screen.findByText(/パスワードは 8〜128 文字/)).toBeInTheDocument();
      expect(fn).not.toHaveBeenCalled();
    }
  });

  it("passwordLength は NFKC 正規化後の文字数（絵文字は 1 文字）", () => {
    expect(passwordLength("ａｂｃ")).toBe(3);
    expect(passwordLength("😀😀")).toBe(2);
  });

  it("氏名が空・全角空白のみ、メール形式不正はクライアントで止める（送信しない）", () => {
    const { fn } = mockFetch(() => jsonResponse(202, { status: "accepted" }));
    render(<RegisterForm />);
    fill({ email: "not-an-email", password: GOOD_PW, name: "　　" });
    submit();
    expect(fn).not.toHaveBeenCalled();
    expect(screen.getByText("メールアドレスの形式を確認してください")).toBeInTheDocument();
    expect(screen.getByText(/氏名は 1〜50 文字/)).toBeInTheDocument();
  });

  it("202: フォームが消え、案内と /login へのリンクが出る。送信本文は email・password・name だけ（任意項目は未入力なら送らない）", async () => {
    const { calls } = mockFetch(() => jsonResponse(202, { status: "accepted" }));
    render(<RegisterForm />);
    fill({ email: " New@Example.com ", password: GOOD_PW, name: " デモ 太郎 " });
    submit();
    expect(await screen.findByTestId("register-done")).toHaveTextContent("登録を受け付けました");
    expect(screen.queryByTestId("register-submit")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ログイン画面へ" })).toHaveAttribute("href", "/login");
    expect(calls[0].url).toBe("/api/auth/register");
    expect(calls[0].body).toEqual({ email: "New@Example.com", password: GOOD_PW, name: "デモ 太郎" });
  });

  it("任意項目（生年月日・性別・パーソナライズ）は入力したときだけ送る", async () => {
    const { calls } = mockFetch(() => jsonResponse(202, { status: "accepted" }));
    render(<RegisterForm />);
    fill({ email: "new@example.com", password: GOOD_PW, name: "デモ" });
    fireEvent.change(screen.getByLabelText(/^生年月日/), { target: { value: "1990-02-03" } });
    fireEvent.change(screen.getByLabelText(/^性別/), { target: { value: "female" } });
    fireEvent.click(screen.getByLabelText(/おすすめの表示に使う/));
    submit();
    await screen.findByTestId("register-done");
    expect(calls[0].body).toEqual({
      email: "new@example.com",
      password: GOOD_PW,
      name: "デモ",
      birth_date: "1990-02-03",
      gender: "female",
      personalize_opt_in: true,
    });
  });

  it("400 の fields は項目ごとに表示する（未知の項目名は出さない）", async () => {
    mockFetch(() =>
      jsonResponse(400, {
        code: "validation_error",
        fields: [
          { name: "email", reason: "format" },
          { name: "name", reason: "required" },
          { name: "internal_secret_field", reason: "format" },
        ],
      }),
    );
    render(<RegisterForm />);
    fill({ email: "new@example.com", password: GOOD_PW, name: "デモ" });
    submit();
    expect(await screen.findByText("メールアドレスの形式を確認してください")).toBeInTheDocument();
    expect(screen.getByText(/氏名は 1〜50 文字/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("internal_secret_field");
  });

  it("422 weak_password はパスワード欄、422 unsupported_value はメール欄に出る", async () => {
    mockFetch(() => jsonResponse(422, { code: "weak_password", field: "password" }));
    const { unmount } = render(<RegisterForm />);
    fill({ email: "new@example.com", password: "password1", name: "デモ" }); // pragma: allowlist secret
    submit();
    expect(await screen.findByText("よくあるパスワードやメールアドレスと同じ値は使えません", { selector: "p[role=alert]" })).toBeInTheDocument();
    unmount();

    vi.unstubAllGlobals();
    mockFetch(() => jsonResponse(422, { code: "unsupported_value", field: "email" }));
    render(<RegisterForm />);
    fill({ email: "x@sub.example.org", password: GOOD_PW, name: "デモ" });
    submit();
    expect(await screen.findByText("このサイトでは使えないメールアドレスです")).toBeInTheDocument();
  });

  it("429・503 はフォーム上部の alert。送信中はボタン無効", async () => {
    let resolve!: (r: Response) => void;
    mockFetch(() => new Promise<Response>((r) => (resolve = r)));
    render(<RegisterForm />);
    fill({ email: "new@example.com", password: GOOD_PW, name: "デモ" });
    submit();
    await waitFor(() => expect(screen.getByTestId("register-submit")).toBeDisabled());
    resolve(jsonResponse(429, { code: "rate_limited" }));
    expect(await screen.findByTestId("register-error")).toHaveTextContent("試行が多すぎます");
    expect(screen.getByTestId("register-submit")).not.toBeDisabled();
  });
});
