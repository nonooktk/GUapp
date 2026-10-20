import type { Metadata } from "next";
import { notFound } from "next/navigation";
import AdminProductEditor from "@/components/admin/AdminProductEditor";
import LoadError from "@/components/LoadError";
import { loadAdminProduct } from "@/lib/server/admin";

/**
 * 商品の編集 DS-SCR-015-2（設計仕様書 P2 追補c 6.4、テスト UT-WEB-44・45・AT-31・AT-32）。公開・価格・在庫だけを編集する。
 * `productId` は 1 以上の整数の文字列（形が違えば 404）。非公開の商品も管理者には表示する（API が 404 を返すのは存在しないときだけ）。
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "商品の編集 | 管理 | GU EC サイト", robots: { index: false, follow: false } };

export default async function AdminProductPage({ params }: PageProps<"/admin/products/[productId]">) {
  const { productId } = await params;
  if (!/^[1-9][0-9]{0,18}$/.test(productId)) notFound();

  const result = await loadAdminProduct(productId);
  if (result.kind === "not_found") notFound();
  if (result.kind !== "ok") return <LoadError what="商品" />;

  return <AdminProductEditor product={result.data} />;
}
