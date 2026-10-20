"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import AdminStockRow from "@/components/admin/AdminStockRow";
import Button from "@/components/Button";
import ConfirmDialog from "@/components/ConfirmDialog";
import { controlClass } from "@/components/Form";
import { useToast } from "@/components/Toast";
import { ADMIN_MESSAGES, adminErrorMessage, adminFormatMessage, adminRangeMessage, isSessionExpired } from "@/lib/admin-messages";
import { ADMIN_LOGIN_EXPIRED_PATH, type AdminProductDetail } from "@/lib/admin-types";
import { adminErrorParts, updateAdminProduct } from "@/lib/client/admin-api";

/**
 * 商品の編集 DS-SCR-015-2（設計仕様書 P2 追補c 6.4・DS-DEC-113・116、テスト UT-WEB-45・AT-32）。公開・価格・在庫だけ（名前・説明・画像は編集しない）。
 * - 公開状態の切り替えは `ConfirmDialog` を経る（キャンセルでは送らない）。価格の保存は確認なし
 * - 送るのは**変更した項目と対応する `expected_*` だけ**。`expected_*` には画面が表示していた値（最後に確認できたサーバーの値）を入れる
 * - 価格は 1 以上 1,000,000 以下の整数。範囲外・形の違いは送信せず入力欄の下に表示する
 * - 409 `stale_data` は `current` の値で表示を更新し、「他の操作で値が変わっていました（現在の値：N）…」を出す。401 は `/admin/login?expired=1`
 * - 在庫は行（AdminStockRow）ごとに保存する
 */

const MAX_PRICE = 1_000_000;

type PriceInput = { kind: "ok"; value: number } | { kind: "empty" } | { kind: "format" } | { kind: "range" };

function parsePriceInput(raw: string): PriceInput {
  const s = raw.trim();
  if (s === "") return { kind: "empty" };
  if (!/^-?\d+$/.test(s)) return { kind: "format" };
  if (s.length > 9) return { kind: "range" };
  const n = Number(s);
  return n < 1 || n > MAX_PRICE ? { kind: "range" } : { kind: "ok", value: n };
}

export default function AdminProductEditor({ product }: { product: AdminProductDetail }) {
  const router = useRouter();
  const toast = useToast();
  const [published, setPublished] = useState(product.published);
  const [serverPrice, setServerPrice] = useState(product.price_incl_tax);
  const [priceInput, setPriceInput] = useState(String(product.price_incl_tax));
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [priceError, setPriceError] = useState<string | null>(null);
  const [busyKind, setBusyKind] = useState<"publish" | "price" | null>(null);
  const inflight = useRef(false);

  const priceUnchanged = priceInput.trim() === String(serverPrice);

  /** 失敗の共通処理。セッション切れは移動し、`stale_data` は表示を現在の値に直す。表示する文言を返す */
  const handleFailure = (err: unknown, onStale: (current: unknown) => void): string | null => {
    const { status, body } = adminErrorParts(err);
    if (isSessionExpired(status, body)) {
      router.replace(ADMIN_LOGIN_EXPIRED_PATH);
      return null;
    }
    if (body?.code === "stale_data") onStale(body.current);
    return adminErrorMessage(status, body);
  };

  const togglePublish = async () => {
    if (inflight.current) return;
    inflight.current = true;
    setBusyKind("publish");
    setPublishError(null);
    const next = !published;
    try {
      const r = await updateAdminProduct(product.product_id, { published: next, expected_published: published });
      setPublished(r.published);
      toast.show(r.changed ? { kind: "success", message: r.published ? "公開しました" : "非公開にしました" } : { kind: "info", message: ADMIN_MESSAGES.noChange });
      setConfirmOpen(false);
    } catch (err) {
      setConfirmOpen(false);
      const message = handleFailure(err, (current) => {
        if (typeof current === "boolean") setPublished(current);
      });
      if (message) setPublishError(message);
    } finally {
      inflight.current = false;
      setBusyKind(null);
    }
  };

  const savePrice = async () => {
    if (inflight.current) return;
    const parsed = parsePriceInput(priceInput);
    if (parsed.kind !== "ok") {
      setPriceError(parsed.kind === "empty" ? "価格を入力してください" : parsed.kind === "format" ? adminFormatMessage("price_incl_tax") : (adminRangeMessage("price_incl_tax") ?? ""));
      return;
    }
    setPriceError(null);
    inflight.current = true;
    setBusyKind("price");
    try {
      const r = await updateAdminProduct(product.product_id, { price_incl_tax: parsed.value, expected_price_incl_tax: serverPrice });
      setServerPrice(r.price_incl_tax);
      setPriceInput(String(r.price_incl_tax));
      toast.show(r.changed ? { kind: "success", message: ADMIN_MESSAGES.saved } : { kind: "info", message: ADMIN_MESSAGES.noChange });
    } catch (err) {
      const message = handleFailure(err, (current) => {
        if (typeof current === "number" && Number.isInteger(current)) {
          setServerPrice(current);
          setPriceInput(String(current));
        }
      });
      if (message) setPriceError(message);
    } finally {
      inflight.current = false;
      setBusyKind(null);
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-light tracking-heading" data-testid="admin-product-name">
          {product.name}
        </h1>
        <Link href="/admin/products" className="inline-flex h-9 items-center text-sm underline underline-offset-2">
          一覧へ戻る
        </Link>
      </div>

      <section aria-labelledby="publish-heading" className="space-y-2 rounded-sm border border-line p-4">
        <h2 id="publish-heading" className="text-base font-bold tracking-heading">
          公開状態
        </h2>
        <div className="flex flex-wrap items-center gap-4">
          <p className="text-sm">
            現在：<strong data-testid="admin-published-state">{published ? "公開" : "非公開"}</strong>
          </p>
          <Button variant="secondary" size="md" onClick={() => setConfirmOpen(true)} disabled={busyKind !== null} data-testid="admin-publish-toggle">
            {published ? "非公開にする" : "公開する"}
          </Button>
        </div>
        {publishError && (
          <p role="alert" className="text-sm font-bold text-danger" data-testid="admin-publish-error">
            ⚠ {publishError}
          </p>
        )}
      </section>

      <section aria-labelledby="price-heading" className="space-y-2 rounded-sm border border-line p-4">
        <h2 id="price-heading" className="text-base font-bold tracking-heading">
          価格
        </h2>
        <div className="flex flex-wrap items-start gap-3">
          <div>
            <label htmlFor="admin-price" className="mb-1 block text-sm font-bold">
              価格（税込）
            </label>
            <div className="flex items-center gap-2">
              <input
                id="admin-price"
                inputMode="numeric"
                autoComplete="off"
                value={priceInput}
                onChange={(e) => {
                  setPriceInput(e.target.value);
                  setPriceError(null);
                }}
                aria-invalid={priceError ? true : undefined}
                aria-describedby={priceError ? "admin-price-error" : undefined}
                className={`${controlClass} w-36 text-right tabular-nums`}
                data-testid="admin-price-input"
              />
              <span className="text-sm">円</span>
            </div>
            {priceError && (
              <p id="admin-price-error" role="alert" className="mt-1 max-w-sm text-sm text-danger" data-testid="admin-price-error">
                {priceError}
              </p>
            )}
          </div>
          <div className="pt-6">
            <Button variant="primary" size="md" onClick={savePrice} busy={busyKind === "price"} disabled={priceUnchanged || busyKind !== null} data-testid="admin-price-save">
              価格を保存
            </Button>
          </div>
        </div>
      </section>

      <section aria-labelledby="stock-heading" className="space-y-2">
        <h2 id="stock-heading" className="text-base font-bold tracking-heading">
          在庫（バリエーションごと）
        </h2>
        <div className="relative overflow-x-auto rounded-sm border border-line">
          <table className="w-full min-w-[720px] border-collapse text-sm">
            <caption className="sr-only">バリエーションごとの在庫</caption>
            <thead className="bg-line/40 text-left">
              <tr>
                <th scope="col" className="px-3 py-2">SKU</th>
                <th scope="col" className="px-3 py-2">色</th>
                <th scope="col" className="px-3 py-2">サイズ</th>
                <th scope="col" className="px-3 py-2">在庫</th>
                <th scope="col" className="px-3 py-2">再入荷待ち</th>
                <th scope="col" className="px-3 py-2">
                  <span className="sr-only">操作</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {product.variants.map((v) => (
                <AdminStockRow key={v.variant_id} variant={v} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <ConfirmDialog
        open={confirmOpen}
        title={published ? "非公開にしますか" : "公開しますか"}
        description={published ? "公開を止めると、お客様は商品を見られなくなります" : "公開すると、お客様が商品を見られるようになります"}
        confirmLabel={published ? "非公開にする" : "公開する"}
        destructive={published}
        busy={busyKind === "publish"}
        onConfirm={togglePublish}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
