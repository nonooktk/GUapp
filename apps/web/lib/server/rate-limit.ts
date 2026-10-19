/**
 * BFF・ページの回数制限（セキュリティ強化 S1）。IP ごとの固定窓（60 秒）カウンタ。
 *
 * - 判定は純粋関数＋プロセス内メモリ。proxy.ts から呼ぶため `server-only` を付けない（Vitest から直接テストできる）
 * - **複数インスタンスでは共有されない**。1 インスタンス（F1）なら上限は 1 つのカウンタで効く。
 *   インスタンスを増やすと「上限 × 台数」まで通るので、そのときは Redis など共有ストアに置き換える
 * - 窓が切れたキーは 1 窓ごとにまとめて捨てる。キー数にも上限を置き、IP を大量に変えられても Map が肥大しない
 */

import { DEFAULT_RATE_LIMIT_API_PER_MIN, DEFAULT_RATE_LIMIT_PAGE_PER_MIN } from "@/lib/env-validation";

export const RATE_LIMIT_WINDOW_MS = 60_000;
/** 同時に覚えておく IP（キー）の上限。超えたら古い順に捨てる */
export const RATE_LIMIT_MAX_KEYS = 50_000;

export type RequestKind = "api" | "page" | "static";

/**
 * リクエストの種類。
 * - `/api/*`（BFF の窓口）は "api"
 * - `/_next/*`（ビルド成果物・dev の HMR など）と、拡張子付きの静的ファイル（`/products/031/1.jpg` など public 配下）は数えない
 * - それ以外（ページ・RSC・prefetch）は "page"
 */
export function classifyPath(pathname: string): RequestKind {
  if (pathname === "/api" || pathname.startsWith("/api/")) return "api";
  if (pathname.startsWith("/_next/") || pathname.startsWith("/__nextjs")) return "static";
  const last = pathname.slice(pathname.lastIndexOf("/") + 1);
  if (/\.[A-Za-z0-9]{1,10}$/.test(last)) return "static";
  return "page";
}

export interface RateLimitResult {
  allowed: boolean;
  limit: number;
  /** この窓での回数（今回を含む） */
  count: number;
  /** 窓が切れるまでの秒（1 以上）。`Retry-After` に使う */
  retryAfterSec: number;
}

interface Bucket {
  count: number;
  resetAt: number;
}

export class FixedWindowCounter {
  private readonly buckets = new Map<string, Bucket>();
  private nextSweepAt = 0;

  constructor(
    private readonly windowMs: number = RATE_LIMIT_WINDOW_MS,
    private readonly now: () => number = () => Date.now(),
    private readonly maxKeys: number = RATE_LIMIT_MAX_KEYS,
  ) {}

  /** 覚えているキーの数（テスト・監視用） */
  get size(): number {
    return this.buckets.size;
  }

  /** 1 回数えて、上限内かを返す。上限を超えた回も数えるが、窓が切れれば 1 から数え直す */
  hit(key: string, limit: number): RateLimitResult {
    const now = this.now();
    this.sweep(now);

    let bucket = this.buckets.get(key);
    if (!bucket || bucket.resetAt <= now) {
      if (!bucket && this.buckets.size >= this.maxKeys) {
        // Map は挿入順。最も古いキーを捨てる
        const oldest = this.buckets.keys().next();
        if (!oldest.done) this.buckets.delete(oldest.value);
      }
      bucket = { count: 0, resetAt: now + this.windowMs };
      this.buckets.set(key, bucket);
    }
    bucket.count += 1;

    return {
      allowed: bucket.count <= limit,
      limit,
      count: bucket.count,
      retryAfterSec: Math.max(1, Math.ceil((bucket.resetAt - now) / 1000)),
    };
  }

  /** 窓が切れたキーを捨てる（1 窓に 1 回だけ全件を見る） */
  private sweep(now: number): void {
    if (now < this.nextSweepAt) return;
    this.nextSweepAt = now + this.windowMs;
    for (const [key, bucket] of this.buckets) {
      if (bucket.resetAt <= now) this.buckets.delete(key);
    }
  }
}

export interface RateLimitConfig {
  apiPerMin: number;
  pagePerMin: number;
}

export const DEFAULT_RATE_LIMIT_CONFIG: RateLimitConfig = {
  apiPerMin: DEFAULT_RATE_LIMIT_API_PER_MIN,
  pagePerMin: DEFAULT_RATE_LIMIT_PAGE_PER_MIN,
};

export interface RateLimiter {
  /** 静的ファイルは数えず null。それ以外は 1 回数えた結果 */
  check(pathname: string, ip: string): RateLimitResult | null;
}

export function createRateLimiter(config: RateLimitConfig, now?: () => number): RateLimiter {
  const counter = new FixedWindowCounter(RATE_LIMIT_WINDOW_MS, now);
  return {
    check(pathname, ip) {
      const kind = classifyPath(pathname);
      if (kind === "static") return null;
      return counter.hit(`${kind}:${ip}`, kind === "api" ? config.apiPerMin : config.pagePerMin);
    },
  };
}

/** 429 の応答。本文は `{"code":"rate_limited"}`、`Retry-After` は窓の残り秒。FastAPI は呼ばない */
export function rateLimitedResponse(retryAfterSec: number): Response {
  return Response.json(
    { code: "rate_limited" },
    { status: 429, headers: { "Retry-After": String(retryAfterSec), "Cache-Control": "no-store" } },
  );
}
