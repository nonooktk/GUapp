import type { ApiErrorBody } from "@/lib/types";

/**
 * BFF のエラー本文（設計仕様書 4.5）を利用者向けの文言にする（純粋関数）。
 * 内部情報は載せない。code ごとに固定文言、422 は limit を差し込む。
 */
export function cartErrorMessage(status: number, body: ApiErrorBody | null): string {
  const code = body?.code;
  switch (code) {
    case "out_of_stock":
      return "在庫切れのため追加できません";
    case "limit_exceeded": {
      if (body?.field === "quantity" && body.limit === 10) return "1 つの商品は 10 点までです";
      if (typeof body?.limit === "number") return `カートに入れられるのは合計 ${body.limit} 点までです`;
      return "数量が上限を超えています";
    }
    case "not_found":
      return "商品が見つかりませんでした";
    case "validation_error":
      return "入力内容に誤りがあります";
    case "forbidden":
      return "ページを再読み込みしてからもう一度お試しください";
    case "upstream_unavailable":
      return "サーバーに接続できません。時間をおいてお試しください";
    default:
      if (status >= 500) return "処理中にエラーが発生しました";
      return "操作に失敗しました";
  }
}

/** カート明細の在庫状態の警告文（設計仕様書 6.6・ST-F009-05）。ok は null */
export function stockWarning(status: string): string | null {
  if (status === "out_of_stock") return "在庫切れのため購入できません";
  if (status === "insufficient") return "在庫が不足しています";
  return null;
}
