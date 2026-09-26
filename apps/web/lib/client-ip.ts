/**
 * 利用者の送信元 IP の判定（純粋関数）。設計仕様書 8.2（X-Forwarded-For）・7.6、ST 実施記録 2026-09-24 の 🟡 対応。
 *
 * 背景: 利用者（ブラウザ）が付けた `X-Forwarded-For` をそのまま FastAPI へ転送すると、
 * ヘッダを付けるだけでゲスト照会のレート制限（100 回/時/IP）を回避でき、他人の IP を名指しして 429 にもできる。
 * Azure App Service の front end は `X-Forwarded-For` に「追記」するため、本番でも利用者が先頭に偽 IP を置ける。
 *
 * 方針: 信頼できる送信元だけを使う。優先順は
 *   1. `X-Client-IP` — App Service の front end が付ける値（利用者は上書きできない）。ただし信頼プロキシの配下（hops が 1 以上）のときだけ
 *   2. `X-Forwarded-For` を右から数えて `trustedProxyHops` 番目 — 信頼プロキシが追記した位置（hops が 1 以上のときだけ）
 *   3. どちらも無ければ利用者送信のヘッダは無視し、接続元（ローカルは 127.0.0.1）にフォールバック
 * hops=0（プロキシ無しで直接受ける構成）では利用者が `X-Client-IP` 自体を付けられるため、①も使わない。
 *
 * 秘密を触らない純粋関数なので `server-only` を付けず、Vitest から直接テストできる（lib/env-validation.ts と同じ置き方）。
 * 実際にリクエストと環境変数を渡すのは lib/server/order-proxy.ts。
 */

export const CLIENT_IP_HEADER = "x-client-ip";
export const FORWARDED_FOR_HEADER_NAME = "x-forwarded-for";
export const FALLBACK_CLIENT_IP = "127.0.0.1";

export interface ResolveClientIpOptions {
  /** 信頼するプロキシのホップ数（環境変数 TRUSTED_PROXY_HOPS。既定 0＝利用者送信の XFF を一切使わない） */
  trustedProxyHops: number;
  /** 接続元 IP（分かる場合）。無ければ 127.0.0.1 */
  connectionIp?: string;
}

const IPV4 = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;
/** IPv6 は厳密な構文検査までは行わず、16 進とコロン・ドット（IPv4 射影）だけで 45 文字以内、コロンを含むものを通す */
const IPV6_LIKE = /^[0-9a-fA-F:.]{2,45}$/;

/** 値が IP アドレスらしいか（`unknown`・空・ヘッダ注入・巨大値を弾く） */
export function isIpLike(value: string): boolean {
  if (IPV4.test(value)) return true;
  return value.includes(":") && IPV6_LIKE.test(value);
}

/**
 * プロキシが付けがちな `IPv4:port` / `[IPv6]:port` の形からポートを落とす。
 * App Service の `X-Forwarded-For` は `IP:port` 形式になることがある。
 */
export function stripPort(value: string): string {
  const v4 = /^(\d{1,3}(?:\.\d{1,3}){3}):\d{1,5}$/.exec(value);
  if (v4) return v4[1];
  const v6 = /^\[([0-9a-fA-F:.]+)\](?::\d{1,5})?$/.exec(value);
  if (v6) return v6[1];
  return value;
}

/** 候補文字列を整えて IP として妥当なら返す。妥当でなければ null */
function normalizeIp(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const value = stripPort(raw.trim());
  return isIpLike(value) ? value : null;
}

/**
 * FastAPI へ渡す利用者 IP を決める。利用者が偽装できる値は使わない。
 * @param headers 受信リクエストのヘッダ
 * @param options trustedProxyHops（既定 0）と接続元 IP
 */
export function resolveClientIp(headers: Headers, options: ResolveClientIpOptions): string {
  const fallback = normalizeIp(options.connectionIp) ?? FALLBACK_CLIENT_IP;
  const hops = Number.isInteger(options.trustedProxyHops) ? options.trustedProxyHops : 0;

  // 信頼プロキシの配下でなければ、利用者が付けられるヘッダは一切使わない
  if (hops >= 1) {
    // ① App Service の front end が付ける X-Client-IP
    const clientIp = normalizeIp(headers.get(CLIENT_IP_HEADER));
    if (clientIp) return clientIp;

    // ② 信頼ホップ数ぶんだけ右から数えた X-Forwarded-For
    const xff = headers.get(FORWARDED_FOR_HEADER_NAME);
    if (xff) {
      const parts = xff.split(",").map((p) => p.trim());
      // 右から hops 番目（hops=1 なら末尾）。要素が足りなければ信頼できる位置が無いのでフォールバック
      const index = parts.length - hops;
      if (index >= 0) {
        const trusted = normalizeIp(parts[index]);
        if (trusted) return trusted;
      }
    }
  }

  // ③ 利用者送信のヘッダは無視して接続元
  return fallback;
}
