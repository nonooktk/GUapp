import type { Metadata } from "next";
import LoadError from "@/components/LoadError";
import LogoutButton from "@/components/LogoutButton";
import OrderHistoryList from "@/components/OrderHistoryList";
import { firstParam, parsePage } from "@/lib/safe-next";
import { loadMe, loadMyOrders } from "@/lib/server/member";

/**
 * マイページ DS-SCR-008（設計仕様書 6.4・DS-API-036・024、テスト AT-13・AT-14・AT-20）。会員情報と注文履歴の一覧（10 件ずつ）。
 * 未ログイン・セッション失効（API が 401）は lib/server/member.ts が `/login?next=/mypage` へ redirect する。
 * 氏名・メールは React のエスケープに任せる（dangerouslySetInnerHTML を使わない）。メール未確認なら案内を出す（再送機能は P2-b に無い。DS-DEC-74）。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "マイページ | GU EC サイト", robots: { index: false } };

export default async function MyPage({ searchParams }: PageProps<"/mypage">) {
  const sp = await searchParams;
  const page = parsePage(firstParam(sp.page));

  const [me, orders] = await Promise.all([loadMe(), loadMyOrders(page)]);
  if (me.kind !== "ok" || orders.kind !== "ok") return <LoadError what="会員情報" />;
  const member = me.data;

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-light tracking-heading">マイページ</h1>
        <LogoutButton />
      </div>

      <section aria-labelledby="member-heading" className="space-y-3 rounded-sm border border-line p-4">
        <h2 id="member-heading" className="text-lg font-light tracking-heading">
          会員情報
        </h2>
        <p className="text-sm" data-testid="member-name">
          <span className="font-bold">{member.name}</span> 様
        </p>
        <p className="break-all text-sm text-fg-muted" data-testid="member-email">
          {member.email}
        </p>
        <p className="text-sm" data-testid="member-verified">
          メール: {member.email_verified ? "確認済み" : "未確認"}
        </p>
        {!member.email_verified && (
          <p role="note" className="rounded-sm border border-danger bg-danger/10 p-3 text-sm" data-testid="unverified-banner">
            ⚠ メールアドレスの確認が済んでいません。届いたメールのリンクを開いてください
          </p>
        )}
      </section>

      <OrderHistoryList history={orders.data} />
    </div>
  );
}
