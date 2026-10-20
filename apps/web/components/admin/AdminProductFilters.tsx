import Button from "@/components/Button";
import { SelectField, TextField } from "@/components/Form";
import { PRODUCT_Q_MAX_LENGTH, type ProductQuery } from "@/lib/admin-query";

/**
 * 商品一覧の検索条件（設計仕様書 P2 追補c 6.4・DS-SCR-015-1、テスト UT-WEB-43）。
 * GET フォームで `/admin/products?q=&visibility=&stock=` に送る（JavaScript なしでも動く。検索条件は URL のクエリに載る）。
 * `page` は付けない（条件を変えたら 1 ページ目から）。値は検査済みの `ProductQuery` から戻す。
 */

export default function AdminProductFilters({ query }: { query: Pick<ProductQuery, "q" | "visibility" | "stock"> }) {
  return (
    <form method="get" action="/admin/products" aria-label="商品の検索" className="flex flex-wrap items-end gap-4 rounded-sm border border-line p-4">
      <div className="w-64">
        <TextField id="admin-q" name="q" label="キーワード（商品名・SKU）" defaultValue={query.q} maxLength={PRODUCT_Q_MAX_LENGTH} autoComplete="off" />
      </div>
      <div className="w-40">
        <SelectField id="admin-visibility" name="visibility" label="公開状態" defaultValue={query.visibility}>
          <option value="all">すべて</option>
          <option value="public">公開</option>
          <option value="private">非公開</option>
        </SelectField>
      </div>
      <div className="w-48">
        <SelectField id="admin-stock" name="stock" label="在庫" defaultValue={query.stock}>
          <option value="all">すべて</option>
          <option value="out">在庫 0 の SKU あり</option>
        </SelectField>
      </div>
      <Button type="submit" variant="primary" size="md">
        検索
      </Button>
    </form>
  );
}
