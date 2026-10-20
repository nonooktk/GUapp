import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LoginForm from "@/components/LoginForm";
import { clearCookies, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";

// テスト設計書 UT-WEB-16（ログインフォーム。DS-SCR-007）。設計仕様書 6.3・DS-DEC-71・85
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

function fill(email: string, password: string) {
  fireEvent.change(screen.getByLabelText(/^メールアドレス/), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^パスワード/), { target: { value: password } });
}
const submit = () => fireEvent.click(screen.getByTestId("login-submit"));

describe("UT-WEB-16 ログインフォーム", () => {
  it("デモの注意書きが常に出る。パスワード・登録・再設定へのリンクがある", () => {
    render(<LoginForm />);
    expect(screen.getByRole("note", { name: "デモに関する注意" })).toHaveTextContent("demo@example.com");
    expect(screen.getByRole("link", { name: "パスワードをお忘れの方" })).toHaveAttribute("href", "/password-reset");
    expect(screen.getByRole("link", { name: "会員登録はこちら" })).toHaveAttribute("href", "/register");
  });

  it("必須が空なら送信せず項目にエラーを出す", () => {
    const { fn } = mockFetch(() => jsonResponse(200, {}));
    render(<LoginForm />);
    submit();
    expect(fn).not.toHaveBeenCalled();
    expect(screen.getAllByRole("alert")).toHaveLength(2);
  });

  it("成功: next（safeNext 済み）へ router.replace し、router.refresh でヘッダーを描き直す", async () => {
    const { calls } = mockFetch(() => jsonResponse(200, { member: { name: "デモ 一郎", email_verified: true } }));
    render(<LoginForm next="/checkout" />);
    fill("demo-member1@example.com", "dummy-password-1");
    submit();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/checkout"));
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/auth/login");
    expect(calls[0].body).toEqual({ email: "demo-member1@example.com", password: "dummy-password-1" });
    expect(calls[0].headers.get("X-CSRF-Token")).toBeTruthy();
  });

  it("next が許可リスト外（//evil.example）なら /mypage、next なしも /mypage", async () => {
    mockFetch(() => jsonResponse(200, { member: { name: "x", email_verified: true } }));
    const { unmount } = render(<LoginForm next="//evil.example" />);
    fill("a@example.com", "pw");
    submit();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/mypage"));
    unmount();

    replace.mockReset();
    render(<LoginForm />);
    fill("a@example.com", "pw");
    submit();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/mypage"));
  });

  it.each([
    [401, { code: "invalid_credentials" }, "メールアドレスまたはパスワードが違います"],
    [403, { code: "account_locked" }, "ログインを一時的に止めています。しばらくしてからもう一度お試しください"],
    [429, { code: "rate_limited" }, "試行が多すぎます。しばらくしてからお試しください"],
    [503, { code: "upstream_unavailable" }, "接続できません"],
  ])("%i の文言（入力済みのメールは残り、パスワードは空になる）", async (status, body, message) => {
    mockFetch(() => jsonResponse(status, body));
    render(<LoginForm />);
    fill("demo-member1@example.com", "wrong-password");
    submit();
    expect(await screen.findByTestId("login-error")).toHaveTextContent(message);
    expect(screen.getByLabelText(/^メールアドレス/)).toHaveValue("demo-member1@example.com");
    expect(screen.getByLabelText(/^パスワード/)).toHaveValue("");
    expect(replace).not.toHaveBeenCalled();
    // 401 は「どちらが違うか」を書かない
    expect(screen.getByTestId("login-error").textContent).not.toMatch(/登録されていません|存在しません/);
    // 内部のコードを画面に出さない
    expect(screen.getByTestId("login-error").textContent).not.toMatch(/invalid_credentials|account_locked|rate_limited/);
  });

  it("送信中はボタンが無効で処理中表示になり、連打しても 2 回目の送信が起きない", async () => {
    let resolve!: (r: Response) => void;
    const { fn } = mockFetch(() => new Promise<Response>((r) => (resolve = r)));
    render(<LoginForm />);
    fill("a@example.com", "pw");
    submit();
    const button = await screen.findByTestId("login-submit");
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveTextContent("ログイン中…");
    fireEvent.submit(button.closest("form")!);
    fireEvent.submit(button.closest("form")!);
    expect(fn).toHaveBeenCalledTimes(1);
    await act(async () => resolve(jsonResponse(200, { member: { name: "x", email_verified: true } })));
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(1));
  });

  it("?reset=1 のときパスワード変更後の案内を出す", () => {
    render(<LoginForm resetDone />);
    expect(screen.getByTestId("reset-done")).toHaveTextContent("パスワードを変更しました。ログインしてください");
  });
});
