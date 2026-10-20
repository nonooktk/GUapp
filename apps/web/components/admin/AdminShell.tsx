"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import Button from "@/components/Button";
import { ADMIN_LOGIN_PATH } from "@/lib/admin-types";
import { adminLogout } from "@/lib/client/admin-api";

/**
 * 管理画面の共通シェル（設計仕様書 P2 追補c 6.2・DS-DEC-122、テスト UT-WEB-41・AT-30）。`/admin/login` 以外の管理ページに付く。
 * - 顧客向けのヘッダー・フッター・カート・AI アシスタントの起動ボタン・期間限定公開の帯は出さない。
 *   「管理」の見出しを常に出し、背景の帯を暗い色にして顧客向けと見分ける。公開サイトへのリンクは置かない
 * - メニューの現在のページに `aria-current="page"`（商品の編集のような下位のパスでも親のメニューが現在地）。
 *   「設定」は DS-SCR-016 を作ったとき（`settingsEnabled`）だけ出す
 * - ログアウトは `POST /admin/api/auth/logout`。成功・失敗にかかわらず `/admin/login` へ移し、画面を描き直す
 */

export interface AdminShellProps {
  loginId: string;
  /** 設定の画面（DS-SCR-016）を提供するか。削る順番④で作らない場合は false にしてメニューからも外す */
  settingsEnabled?: boolean;
  children: ReactNode;
}

interface MenuItem {
  href: string;
  label: string;
}

const MENU: readonly MenuItem[] = [
  { href: "/admin/products", label: "商品" },
  { href: "/admin/orders", label: "注文" },
  { href: "/admin/settings", label: "設定" },
];

function isCurrent(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function AdminShell({ loginId, settingsEnabled = true, children }: AdminShellProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [busy, setBusy] = useState(false);

  const onLogout = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await adminLogout();
    } catch {
      // 失敗しても BFF は `asid` の削除 Cookie を返している。ログイン画面へ移す
    }
    router.replace(ADMIN_LOGIN_PATH);
    router.refresh();
  };

  const items = MENU.filter((m) => settingsEnabled || m.href !== "/admin/settings");

  return (
    <>
      <header className="bg-primary text-primary-fg" data-testid="admin-header">
        <div className="mx-auto flex w-full max-w-page flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link href="/admin/products" className="text-base font-bold tracking-heading">
            GU EC <span data-testid="admin-title">管理</span>
          </Link>
          <nav aria-label="管理メニュー" className="flex flex-1 items-center gap-1">
            {items.map((m) => {
              const current = isCurrent(pathname, m.href);
              return (
                <Link
                  key={m.href}
                  href={m.href}
                  aria-current={current ? "page" : undefined}
                  className={`inline-flex h-9 items-center rounded-pill px-4 text-sm hover:bg-white/10 ${current ? "bg-white/20 font-bold" : ""}`}
                >
                  {m.label}
                </Link>
              );
            })}
          </nav>
          <div className="flex items-center gap-3 text-sm">
            <span data-testid="admin-staff-id" className="break-all">
              {loginId}
            </span>
            <Button variant="secondary" size="md" onClick={onLogout} busy={busy} busyLabel="ログアウト中…" data-testid="admin-logout">
              ログアウト
            </Button>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-page flex-1 px-4 py-6">
        {children}
      </main>
    </>
  );
}
