import type { Metadata } from "next";
import { redirect } from "next/navigation";
import LoginForm from "@/components/LoginForm";
import { firstParam, safeNext } from "@/lib/safe-next";
import { getMemberOrNull } from "@/lib/server/member";

/**
 * ログイン DS-SCR-007（設計仕様書 6.3）。`?next=` は safeNext（許可リストの完全一致）、`?reset=1` はパスワード変更後の案内。
 * すでにログイン済みなら遷移先へ移す。Cookie `sid` が「ある」だけでは移さない（失効した `sid` が残っていると、
 * /mypage が 401 → /login → /mypage … と戻り合ってしまうため）。`GET /me` で有効なときだけ移し、失効していればフォームを出す。
 * Next.js 16 では searchParams が Promise。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "ログイン | GU EC サイト" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const sp = await searchParams;
  const next = safeNext(firstParam(sp.next));
  const resetDone = firstParam(sp.reset) === "1";

  const member = await getMemberOrNull();
  if (member) redirect(next);

  return <LoginForm next={next} resetDone={resetDone} />;
}
