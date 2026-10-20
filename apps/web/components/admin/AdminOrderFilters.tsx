import Button from "@/components/Button";
import { SelectField, TextField } from "@/components/Form";
import type { OrderQuery } from "@/lib/admin-query";
import { ADMIN_ORDER_STATUS_OPTIONS } from "@/lib/admin-types";

/**
 * 注文一覧の検索条件（設計仕様書 P2 追補c 6.5・DS-SCR-015-3、テスト UT-WEB-46・ST-SEC-87）。
 * GET フォームで `/admin/orders?status=&receive_method=&from=&to=&order_number=&email=` に送る（検索条件は URL のクエリに載る）。
 * 期間は `type="date"`（JST の暦日）。形が違う入力は検査（parseOrderQuery）が FastAPI に渡さず、`errors` を項目の下に出す。
 * メールは完全一致（部分一致・氏名・電話での検索は作らない。DS-DEC-118）。`apiError` は FastAPI の 400／422 の文言。
 */

export default function AdminOrderFilters({ query, apiError }: { query: Pick<OrderQuery, "values" | "errors">; apiError?: string | null }) {
  const { values, errors } = query;
  return (
    <form method="get" action="/admin/orders" aria-label="注文の検索" className="space-y-4 rounded-sm border border-line p-4" noValidate>
      <div className="flex flex-wrap items-start gap-4">
        <div className="w-44">
          <SelectField id="admin-status" name="status" label="状態" defaultValue={values.status}>
            <option value="all">すべて</option>
            {ADMIN_ORDER_STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </SelectField>
        </div>
        <div className="w-40">
          <SelectField id="admin-receive-method" name="receive_method" label="受け取り" defaultValue={values.receive_method}>
            <option value="all">すべて</option>
            <option value="delivery">配送</option>
            <option value="store">店舗受け取り</option>
          </SelectField>
        </div>
        <div className="w-48">
          <TextField id="admin-from" name="from" type="date" label="期間（開始）" defaultValue={values.from} error={errors.from} />
        </div>
        <div className="w-48">
          <TextField id="admin-to" name="to" type="date" label="期間（終了）" defaultValue={values.to} error={errors.to} />
        </div>
      </div>
      <div className="flex flex-wrap items-start gap-4">
        <div className="w-64">
          <TextField
            id="admin-order-number"
            name="order_number"
            label="注文番号"
            placeholder="GU-261024-ABCDEFGH"
            defaultValue={values.order_number}
            error={errors.order_number}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div className="w-72">
          <TextField
            id="admin-email"
            name="email"
            label="メール（完全一致）"
            defaultValue={values.email}
            error={errors.email}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div className="pt-6">
          <Button type="submit" variant="primary" size="md">
            検索
          </Button>
        </div>
      </div>
      {apiError && (
        <p role="alert" className="text-sm font-bold text-danger" data-testid="admin-orders-api-error">
          ⚠ {apiError}
        </p>
      )}
    </form>
  );
}
