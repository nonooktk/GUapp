import { AUTH_DEMO_NOTICE } from "@/lib/auth-messages";

/** 登録・パスワード再設定の要求・ログインに常時表示するデモの注意書き（設計仕様書 6.3・DS-DEC-47 の延長）。本番でも出し分けない */
export default function AuthDemoNotice() {
  return (
    <div role="note" aria-label="デモに関する注意" className="rounded-sm border border-line bg-line/40 p-4 text-sm" data-testid="auth-demo-notice">
      <p className="text-fg-muted">{AUTH_DEMO_NOTICE}</p>
    </div>
  );
}
