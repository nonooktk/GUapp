import { pickAdminBody, proxyAdminRequest } from "@/lib/server/admin-proxy";
import { readJsonBody, validationError } from "@/lib/server/cart-proxy";
import { verifyCsrf } from "@/lib/server/csrf";

/**
 * 設定の更新 BFF（DS-API-052a 取り次ぎ。設計仕様書 P2 追補c 4.3・4.5・DS-DEC-119、テスト IT-BFF-051・053〜055）。
 * - 白リスト：tax_rate・shipping_fee・free_shipping_threshold と対応する `expected_*`。`payment_timeout_minutes` は更新できないので落とす
 * - 型が違えば 400（FastAPI を呼ばない）。`expected_*` の対応・範囲・形（`^[0-9]\.[0-9]{2}$`）は FastAPI が判定する
 */

export const dynamic = "force-dynamic";

export async function PATCH(request: Request) {
  const denied = verifyCsrf(request);
  if (denied) return denied;

  const parsed = await readJsonBody(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.body) return validationError(request, [{ name: "body", reason: "format" }]);

  const { payload, fields } = pickAdminBody(parsed.body, {
    fields: {
      tax_rate: "string",
      shipping_fee: "int",
      free_shipping_threshold: "int",
      expected_tax_rate: "string",
      expected_shipping_fee: "int",
      expected_free_shipping_threshold: "int",
    },
  });
  if (fields.length > 0) return validationError(request, fields);

  return proxyAdminRequest(request, "/admin/settings", { mode: "update", method: "PATCH", json: payload });
}
