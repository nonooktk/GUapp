"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import Button from "@/components/Button";
import ConfirmDialog from "@/components/ConfirmDialog";
import { TextField } from "@/components/Form";
import { useToast } from "@/components/Toast";
import { ADMIN_MESSAGES, adminErrorMessage, isSessionExpired } from "@/lib/admin-messages";
import { ADMIN_LOGIN_EXPIRED_PATH, type AdminOrderStatus, type AdminTransition } from "@/lib/admin-types";
import { adminErrorParts, updateAdminOrderStatus } from "@/lib/client/admin-api";

/**
 * 注文状態の更新パネル（設計仕様書 P2 追補c 6.5・DS-DEC-117・113、テスト UT-WEB-47・AT-33・AT-34）。
 * - 「次の操作」のボタンは `transitions`（API の `available_transitions`）だけを描く。画面側に遷移表を置かない
 * - 更新先が `shipped` で `accepts_tracking_number` が真のときだけ、追跡番号の入力欄（任意）を同じ枠に出す。形は `^[A-Za-z0-9-]{1,50}$`
 * - 押すと `ConfirmDialog`（「状態を『{ラベル}』に更新します。元には戻せません」）を経てから PATCH する。キャンセルでは送らない
 * - 409 `invalid_transition` は「この注文の状態はすでに変わっています。画面を更新しました」（トースト）を出して再読み込み
 * - 401（セッション切れ）は `/admin/login?expired=1` へ移す。それ以外の失敗は枠の中の `role="alert"`
 * - `expected_*` は使わない（更新先から更新前の状態が一意に決まる。DS-DEC-113）
 */

export interface AdminStatusPanelProps {
  orderNumber: string;
  status: AdminOrderStatus;
  statusLabel: string;
  trackingNumber: string | null;
  transitions: AdminTransition[];
}

const TRACKING_SHAPE = /^[A-Za-z0-9-]{1,50}$/;

export default function AdminStatusPanel({ orderNumber, statusLabel, trackingNumber, transitions }: AdminStatusPanelProps) {
  const router = useRouter();
  const toast = useToast();
  const [label, setLabel] = useState(statusLabel);
  const [tracking, setTracking] = useState(trackingNumber);
  const [available, setAvailable] = useState(transitions);
  const [trackingInput, setTrackingInput] = useState("");
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const [pending, setPending] = useState<AdminTransition | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inflight = useRef(false);

  const acceptsTracking = available.some((t) => t.accepts_tracking_number);

  const ask = (t: AdminTransition) => {
    setError(null);
    setTrackingError(null);
    const value = trackingInput.trim();
    if (t.accepts_tracking_number && value !== "" && !TRACKING_SHAPE.test(value)) {
      setTrackingError("追跡番号は半角の英数字とハイフンで 50 文字以内で入力してください");
      document.getElementById("admin-tracking-input")?.focus();
      return;
    }
    setPending(t);
  };

  const confirm = async () => {
    if (!pending || inflight.current) return;
    inflight.current = true;
    setBusy(true);
    const target = pending;
    const value = trackingInput.trim();
    try {
      const result = await updateAdminOrderStatus(orderNumber, target.status, target.accepts_tracking_number && value ? value : undefined);
      setLabel(result.status_label);
      setTracking(result.tracking_number);
      setAvailable(result.available_transitions);
      setTrackingInput("");
      setPending(null);
      toast.show({ kind: "success", message: `状態を『${result.status_label}』に更新しました` });
      router.refresh();
    } catch (err) {
      const { status, body } = adminErrorParts(err);
      setPending(null);
      if (isSessionExpired(status, body)) {
        router.replace(ADMIN_LOGIN_EXPIRED_PATH);
        return;
      }
      if (body?.code === "invalid_transition") {
        toast.show({ kind: "error", message: ADMIN_MESSAGES.invalidTransition });
        router.refresh();
      } else {
        setError(adminErrorMessage(status, body));
      }
    } finally {
      inflight.current = false;
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-status-panel">
      <p className="text-sm">
        現在の状態：<strong data-testid="admin-status-label">{label}</strong>
        {tracking && (
          <span className="ml-4 text-fg-muted">
            追跡番号：<span data-testid="admin-status-tracking">{tracking}</span>
          </span>
        )}
      </p>
      <div role="group" aria-label="次の操作" className="space-y-3 rounded-sm border border-line bg-line/20 p-4">
        <h3 className="text-sm font-bold">次の操作</h3>
        {available.length === 0 ? (
          <p className="text-sm text-fg-muted" data-testid="admin-no-transitions">
            この状態から画面で更新できる操作はありません
          </p>
        ) : (
          <>
            {acceptsTracking && (
              <div className="max-w-sm">
                <TextField
                  id="admin-tracking-input"
                  label="追跡番号（任意）"
                  hint="半角の英数字とハイフン、50 文字まで"
                  autoComplete="off"
                  spellCheck={false}
                  maxLength={50}
                  value={trackingInput}
                  onChange={(e) => setTrackingInput(e.target.value)}
                  error={trackingError}
                />
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              {available.map((t) => (
                <Button key={t.status} variant="primary" size="md" onClick={() => ask(t)} disabled={busy} data-testid={`admin-transition-${t.status}`}>
                  {t.label}にする
                </Button>
              ))}
            </div>
          </>
        )}
        {error && (
          <p role="alert" className="text-sm font-bold text-danger" data-testid="admin-status-error">
            ⚠ {error}
          </p>
        )}
      </div>
      <ConfirmDialog
        open={pending !== null}
        title="注文状態の更新"
        description={pending ? `状態を『${pending.label}』に更新します。元には戻せません` : undefined}
        confirmLabel="更新する"
        busy={busy}
        onConfirm={confirm}
        onCancel={() => setPending(null)}
      />
    </div>
  );
}
