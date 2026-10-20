import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AdminLoginForm from "@/components/admin/AdminLoginForm";
import { clearCookies, CLIENT_CSRF, jsonResponse, mockFetch, setCsrfCookie } from "./helpers/client";

// テスト設計書 UT-WEB-42（管理ログインフォーム。DS-SCR-014）。設計仕様書 P2 追補c 6.3・6.7・DS-DEC-110・121
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
  window.history.replaceState({}, "", "/");
});

function fill(id: string, password: string) {
  fireEvent.change(screen.getByLabelText(/^ログイン ID/), { target: { value: id } });
  fireEvent.change(screen.getByLabelText(/^パスワード/), { target: { value: password } });
}
const submit = () => fireEvent.click(screen.getByTestId("admin-login-submit"));

describe("UT-WEB-42 管理ログインフォーム", () => {
  it("顧客向けのリンク（会員登録・パスワード再設定・公開サイト）を置かない", () => {
    const { container } = render(<AdminLoginForm />);
    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(screen.getByRole("heading", { name: "管理者ログイン" })).toBeInTheDocument();
  });

  it("必須が空なら送信せず項目にエラーを出す", () => {
    const { fn } = mockFetch(() => jsonResponse(200, {}));
    render(<AdminLoginForm />);
    submit();
    expect(fn).not.toHaveBeenCalled();
    expect(screen.getAllByRole("alert")).toHaveLength(2);
  });

  it("成功: 常に /admin/products へ replace し refresh する。本文は login_id・password だけ（前後の空白は除く）", async () => {
    const { calls } = mockFetch(() => jsonResponse(200, { staff: { login_id: "demo-staff", role: "staff" } }));
    render(<AdminLoginForm />);
    fill("  demo-staff ", "dummy-password-1"); // pragma: allowlist secret
    submit();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin/products"));
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/admin/api/auth/login");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toEqual({ login_id: "demo-staff", password: "dummy-password-1" }); // pragma: allowlist secret
    expect(calls[0].headers.get("X-CSRF-Token")).toBe(CLIENT_CSRF);
  });

  it("遷移先の指定（?next=）は受けない: URL に next があっても /admin/products", async () => {
    window.history.replaceState({}, "", "/admin/login?next=//evil.example&expired=0");
    mockFetch(() => jsonResponse(200, { staff: { login_id: "a", role: "staff" } }));
    render(<AdminLoginForm />);
    fill("demo-staff", "pw");
    submit();
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(1));
    expect(replace).toHaveBeenCalledWith("/admin/products");
  });

  it("csrf_token が未発行なら、ログインの前に GET /admin/api/csrf で用意する（FastAPI にカートを作る /api/cart は呼ばない）", async () => {
    clearCookies();
    const { calls } = mockFetch((url) => {
      if (url === "/admin/api/csrf") {
        document.cookie = `csrf_token=${CLIENT_CSRF}; path=/`;
        return jsonResponse(204, null);
      }
      return jsonResponse(200, { staff: { login_id: "a", role: "staff" } });
    });
    render(<AdminLoginForm />);
    fill("demo-staff", "pw");
    submit();
    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(["GET /admin/api/csrf", "POST /admin/api/auth/login"]);
  });

  it.each([
    [401, { code: "invalid_credentials" }, "ログイン ID またはパスワードが違います"],
    [403, { code: "account_locked" }, "ログインを一時的に止めています。しばらくしてからもう一度お試しください"],
    [429, { code: "rate_limited" }, "試行回数が多すぎます。しばらくしてからもう一度お試しください"],
    [503, { code: "upstream_unavailable" }, "サーバーに接続できません。しばらくしてからもう一度お試しください"],
  ])("%i は状態別の文言。ID は残し、パスワードは空にして、遷移しない", async (status, body, message) => {
    mockFetch(() => jsonResponse(status, body));
    render(<AdminLoginForm />);
    fill("demo-staff", "wrong-password"); // pragma: allowlist secret
    submit();
    await waitFor(() => expect(screen.getByTestId("admin-login-error")).toHaveTextContent(message));
    expect(screen.getByLabelText(/^ログイン ID/)).toHaveValue("demo-staff");
    expect(screen.getByLabelText(/^パスワード/)).toHaveValue("");
    expect(replace).not.toHaveBeenCalled();
  });

  it("401 の文言は ID とパスワードのどちらが違うかを書かない。403 は残り時間・回数を書かない", async () => {
    mockFetch(() => jsonResponse(401, { code: "invalid_credentials" }));
    render(<AdminLoginForm />);
    fill("x", "y");
    submit();
    const text = (await screen.findByTestId("admin-login-error")).textContent ?? "";
    expect(text).toContain("ログイン ID またはパスワード");
    expect(text).not.toMatch(/存在|登録されて|回/);
  });

  it("送信中はボタンが無効で「ログイン中…」。連打しても 2 回目を送らない", async () => {
    let resolve!: (r: Response) => void;
    const { fn } = mockFetch(() => new Promise<Response>((r) => (resolve = r)));
    render(<AdminLoginForm />);
    fill("demo-staff", "pw");
    submit();
    await waitFor(() => expect(screen.getByTestId("admin-login-submit")).toBeDisabled());
    expect(screen.getByTestId("admin-login-submit")).toHaveTextContent("ログイン中…");
    fireEvent.submit(screen.getByRole("form", { name: "管理者ログイン" }));
    fireEvent.submit(screen.getByRole("form", { name: "管理者ログイン" }));
    expect(fn).toHaveBeenCalledTimes(1);
    resolve(jsonResponse(200, { staff: { login_id: "a", role: "staff" } }));
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(1));
  });

  it("expired のときだけ有効期限切れの案内を出す", () => {
    const { unmount } = render(<AdminLoginForm expired />);
    expect(screen.getByTestId("admin-expired")).toHaveTextContent("セッションの有効期限が切れました。もう一度ログインしてください");
    unmount();
    render(<AdminLoginForm />);
    expect(screen.queryByTestId("admin-expired")).toBeNull();
  });
});
