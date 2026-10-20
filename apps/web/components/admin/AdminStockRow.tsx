"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import Button from "@/components/Button";
import { controlClass } from "@/components/Form";
import { useToast } from "@/components/Toast";
import { adminErrorMessage, adminFormatMessage, adminRangeMessage, isSessionExpired } from "@/lib/admin-messages";
import { ADMIN_LOGIN_EXPIRED_PATH, type AdminVariant } from "@/lib/admin-types";
import { adminErrorParts, updateAdminStock } from "@/lib/client/admin-api";

/**
 * 在庫の行（設計仕様書 P2 追補c 6.4・DS-DEC-114・115、テスト UT-WEB-44・AT-31）。`<tbody>` の中に置く `<tr>`。
 * - 在庫は行ごとに保存する（絶対値の SET）。`expected_stock` には画面が表示していた値（最後に確認できたサーバーの値）を入れる
 * - 空・負・10000 以上・小数は**送信せず**入力欄の下に表示する（範囲 0〜9999）
 * - 0 から 1 以上にするとき、保存前に「再入荷待ちの N 件にメールを送ります」を出す。保存後のトーストは
 *   「在庫を {前} から {後} に更新しました。再入荷通知の対象は N 件です」（N は応答の `restock_waiting`）
 * - 値が現在と同じなら保存ボタンは無効。409 `stale_data` は `current` で行を更新して案内する
 * - 再入荷待ちの人のメールアドレスは表示しない（件数のみ）
 */

type StockInput = { kind: "ok"; value: number } | { kind: "empty" } | { kind: "format" } | { kind: "range" };

const MAX_STOCK = 9999;

function parseStockInput(raw: string): StockInput {
  const s = raw.trim();
  if (s === "") return { kind: "empty" };
  if (!/^-?\d+$/.test(s)) return { kind: "format" };
  if (s.length > 7) return { kind: "range" };
  const n = Number(s);
  return n < 0 || n > MAX_STOCK ? { kind: "range" } : { kind: "ok", value: n };
}

export default function AdminStockRow({ variant }: { variant: AdminVariant }) {
  const router = useRouter();
  const toast = useToast();
  const [serverStock, setServerStock] = useState(variant.stock);
  const [waiting, setWaiting] = useState(variant.restock_waiting);
  const [input, setInput] = useState(String(variant.stock));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);

  const parsed = parseStockInput(input);
  const unchanged = input.trim() === String(serverStock);
  const restockNote = serverStock === 0 && parsed.kind === "ok" && parsed.value >= 1 && waiting >= 1;
  const errorId = `stock-${variant.variant_id}-error`;
  const noteId = `stock-${variant.variant_id}-note`;

  const save = async () => {
    if (inflight.current) return;
    if (parsed.kind !== "ok") {
      setError(parsed.kind === "empty" ? "在庫を入力してください" : parsed.kind === "format" ? adminFormatMessage("stock") : (adminRangeMessage("stock") ?? ""));
      return;
    }
    setError(null);
    inflight.current = true;
    setBusy(true);
    try {
      const r = await updateAdminStock(variant.variant_id, parsed.value, serverStock);
      setServerStock(r.stock);
      setInput(String(r.stock));
      if (!r.changed) {
        toast.show({ kind: "info", message: "変更はありませんでした" });
      } else {
        const restocked = r.previous_stock === 0 && r.stock >= 1;
        if (restocked) setWaiting(0);
        toast.show({
          kind: "success",
          message: `在庫を ${r.previous_stock} から ${r.stock} に更新しました${restocked ? `。再入荷通知の対象は ${r.restock_waiting} 件です` : ""}`,
        });
      }
    } catch (err) {
      const { status, body } = adminErrorParts(err);
      if (isSessionExpired(status, body)) {
        router.replace(ADMIN_LOGIN_EXPIRED_PATH);
        return;
      }
      if (body?.code === "stale_data" && typeof body.current === "number" && Number.isInteger(body.current)) {
        setServerStock(body.current);
        setInput(String(body.current));
      }
      setError(adminErrorMessage(status, body));
    } finally {
      inflight.current = false;
      setBusy(false);
    }
  };

  return (
    <tr className="border-t border-line align-top" data-testid="admin-stock-row" data-variant-id={variant.variant_id}>
      <td className="px-3 py-2 font-mono text-xs">{variant.sku}</td>
      <td className="px-3 py-2">{variant.color}</td>
      <td className="px-3 py-2">{variant.size}</td>
      <td className="px-3 py-2">
        <label htmlFor={`stock-${variant.variant_id}`} className="sr-only">
          {variant.sku} の在庫
        </label>
        <input
          id={`stock-${variant.variant_id}`}
          inputMode="numeric"
          autoComplete="off"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setError(null);
          }}
          aria-invalid={error ? true : undefined}
          aria-describedby={[restockNote ? noteId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined}
          className={`${controlClass} w-28 text-right tabular-nums`}
          data-testid="admin-stock-input"
        />
        {restockNote && (
          <p id={noteId} className="mt-1 text-xs text-fg-muted" data-testid="admin-restock-note">
            再入荷待ちの {waiting} 件にメールを送ります
          </p>
        )}
        {error && (
          <p id={errorId} role="alert" className="mt-1 max-w-xs text-sm text-danger" data-testid="admin-stock-error">
            {error}
          </p>
        )}
      </td>
      <td className="px-3 py-2 tabular-nums" data-testid="admin-restock-waiting">
        {waiting} 件
      </td>
      <td className="px-3 py-2 text-right">
        <Button variant="secondary" size="md" onClick={save} busy={busy} disabled={unchanged} aria-label={`${variant.sku} の在庫を保存`} data-testid="admin-stock-save">
          保存
        </Button>
      </td>
    </tr>
  );
}
