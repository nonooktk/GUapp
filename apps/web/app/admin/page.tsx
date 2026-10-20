import { redirect } from "next/navigation";
import { ADMIN_HOME_PATH } from "@/lib/admin-types";

/** 管理画面のトップ（設計仕様書 P2 追補c 6.1）。`/admin/products` へ 307 で移す。未ログインならそちらで `/admin/login` へ移る */

export const dynamic = "force-dynamic";

export default function AdminIndexPage() {
  redirect(ADMIN_HOME_PATH);
}
