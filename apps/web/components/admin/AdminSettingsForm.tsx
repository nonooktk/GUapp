"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import Button from "@/components/Button";
import { TextField } from "@/components/Form";
import { useToast } from "@/components/Toast";
import { ADMIN_MESSAGES, adminErrorMessage, adminFormatMessage, adminRangeMessage, isSessionExpired } from "@/lib/admin-messages";
import { ADMIN_LOGIN_EXPIRED_PATH, type AdminSettingItem } from "@/lib/admin-types";
import { adminErrorParts, updateAdminSettings, type SettingsUpdateBody } from "@/lib/client/admin-api";

/**
 * 設定 DS-SCR-016（設計仕様書 P2 追補c 6.6・DS-DEC-113・119、テスト UT-WEB-48・AT-35）。消費税率・送料・送料無料の下限を更新する。
 * - `payment_timeout_minutes` は表示のみ（入力欄を出さない）
 * - 保存は**変更した項目だけ**を `expected_*`（画面が表示していた値）つきで送る。変更がなければ保存ボタンは無効
 * - 範囲外・形の違いは送信せず項目の下に範囲を示す（消費税率 0.00〜0.30、送料 0〜5000、送料無料の下限 0〜100000）。422 も同じ文言
 * - 409 `stale_data` はその項目を `current` で更新して再操作を促す。複数の項目のうち 1 つでも失敗したら全体が更新されない（API の仕様）
 * - 401 は `/admin/login?expired=1`
 */

type EditableKey = "tax_rate" | "shipping_fee" | "free_shipping_threshold";
const EDITABLE_KEYS: readonly EditableKey[] = ["tax_rate", "shipping_fee", "free_shipping_threshold"];

function isEditableKey(key: unknown): key is EditableKey {
  return typeof key === "string" && (EDITABLE_KEYS as readonly string[]).includes(key);
}

const INT_LIMITS: Record<Exclude<EditableKey, "tax_rate">, number> = { shipping_fee: 5000, free_shipping_threshold: 100000 };
const TAX_SHAPE = /^[0-9]\.[0-9]{2}$/;
const TAX_MAX_HUNDREDTHS = 30;

/** 入力 1 項目の検査。通れば null、違えば画面に出す文言 */
function validate(key: EditableKey, raw: string): string | null {
  const s = raw.trim();
  if (s === "") return `${key === "tax_rate" ? "消費税率" : key === "shipping_fee" ? "送料" : "送料無料の下限"}を入力してください`;
  if (key === "tax_rate") {
    if (!TAX_SHAPE.test(s)) return adminFormatMessage(key);
    return Math.round(Number(s) * 100) > TAX_MAX_HUNDREDTHS ? adminRangeMessage(key) : null;
  }
  if (!/^\d+$/.test(s)) return /^-\d+$/.test(s) ? adminRangeMessage(key) : adminFormatMessage(key);
  if (s.length > 7 || Number(s) > INT_LIMITS[key]) return adminRangeMessage(key);
  return null;
}

function toServerValue(key: EditableKey, raw: string): string | number {
  return key === "tax_rate" ? raw.trim() : Number(raw.trim());
}

function fromItems(items: AdminSettingItem[]): Record<EditableKey, string> {
  const out = { tax_rate: "", shipping_fee: "", free_shipping_threshold: "" } as Record<EditableKey, string>;
  for (const it of items) if (isEditableKey(it.key)) out[it.key] = String(it.value);
  return out;
}

function hintOf(it: AdminSettingItem): string | undefined {
  if (it.min === null || it.max === null) return undefined;
  return `${it.min}〜${it.max}${it.unit ? ` ${it.unit}` : ""}`;
}

export default function AdminSettingsForm({ items }: { items: AdminSettingItem[] }) {
  const router = useRouter();
  const toast = useToast();
  const [shown, setShown] = useState(items);
  const [server, setServer] = useState(() => fromItems(items));
  const [inputs, setInputs] = useState(() => fromItems(items));
  const [errors, setErrors] = useState<Partial<Record<EditableKey, string>>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);

  const changedKeys = EDITABLE_KEYS.filter((k) => inputs[k].trim() !== server[k]);
  const canSave = changedKeys.length > 0 && !busy;

  const save = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (inflight.current || changedKeys.length === 0) return;
    const errs: Partial<Record<EditableKey, string>> = {};
    for (const k of changedKeys) {
      const m = validate(k, inputs[k]);
      if (m) errs[k] = m;
    }
    setErrors(errs);
    setFormError(null);
    if (Object.keys(errs).length > 0) return;

    const body: Record<string, string | number> = {};
    for (const k of changedKeys) {
      body[k] = toServerValue(k, inputs[k]);
      body[`expected_${k}`] = toServerValue(k, server[k]);
    }
    inflight.current = true;
    setBusy(true);
    try {
      const r = await updateAdminSettings(body as SettingsUpdateBody);
      setShown(r.items);
      setServer(fromItems(r.items));
      setInputs(fromItems(r.items));
      toast.show(r.changed.length > 0 ? { kind: "success", message: ADMIN_MESSAGES.saved } : { kind: "info", message: ADMIN_MESSAGES.noChange });
    } catch (err) {
      const { status, body: eb } = adminErrorParts(err);
      if (isSessionExpired(status, eb)) {
        router.replace(ADMIN_LOGIN_EXPIRED_PATH);
        return;
      }
      const message = adminErrorMessage(status, eb);
      const fieldName = typeof eb?.field === "string" ? eb.field : (eb?.fields as { name?: unknown }[] | undefined)?.[0]?.name;
      // `expected_tax_rate` のような名前で返る場合も項目に結びつける
      const key = typeof fieldName === "string" ? fieldName.replace(/^expected_/, "") : undefined;
      if (eb?.code === "stale_data" && isEditableKey(key) && (typeof eb.current === "string" || typeof eb.current === "number")) {
        const current = String(eb.current);
        setServer((s) => ({ ...s, [key]: current }));
        setInputs((s) => ({ ...s, [key]: current }));
      }
      if (isEditableKey(key)) setErrors({ [key]: message });
      else setFormError(message);
    } finally {
      inflight.current = false;
      setBusy(false);
    }
  };

  return (
    <form onSubmit={save} noValidate className="max-w-xl space-y-5" aria-label="設定">
      {formError && (
        <p role="alert" className="text-sm font-bold text-danger" data-testid="admin-settings-error">
          ⚠ {formError}
        </p>
      )}
      {shown.map((it) =>
        it.editable && isEditableKey(it.key) ? (
          <TextField
            key={it.key}
            id={`setting-${it.key}`}
            label={it.label}
            hint={hintOf(it)}
            inputMode={it.key === "tax_rate" ? "decimal" : "numeric"}
            autoComplete="off"
            value={inputs[it.key]}
            onChange={(e) => {
              const v = e.target.value;
              setInputs((s) => ({ ...s, [it.key]: v }));
              setErrors((s) => ({ ...s, [it.key]: undefined }));
            }}
            error={errors[it.key]}
          />
        ) : (
          <div key={it.key} className="text-sm" data-testid={`setting-readonly-${it.key}`}>
            <span className="font-bold">{it.label}</span>
            <span className="ml-3 tabular-nums">{String(it.value)}</span>
            <span className="ml-2 text-fg-muted">（変更できません）</span>
          </div>
        ),
      )}
      <Button type="submit" variant="primary" size="lg" busy={busy} disabled={!canSave && !busy} data-testid="admin-settings-save">
        変更を保存
      </Button>
      <p className="text-xs text-fg-muted">
        ※変更は次のアクセスからすべてのお客様の金額に反映されます。注文手続きの途中の方は、金額が変わると注文を確定できず、確認画面からやり直しになります。
      </p>
    </form>
  );
}
