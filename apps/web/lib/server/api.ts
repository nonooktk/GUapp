import "server-only";

import { getEnv } from "@/lib/server/env";

/**
 * FastAPI（`API_BASE_URL` + `/api/v1/...`）を呼ぶ fetch ラッパー（設計仕様書 4.1・4.5）。
 * - `X-Internal-Token` を付与する（DS-DEC-27）
 * - FastAPI の応答本文をそのまま返さず、エラーは `{code, ...許可した詳細}` の形だけ通す（7.2）
 * - 接続不可・タイムアウトは UpstreamUnavailableError（BFF は 503 upstream_unavailable にする）
 */

const API_PREFIX = "/api/v1";
const DEFAULT_TIMEOUT_MS = 5000;

/** 設計仕様書 4.5 の本文形式で許可する詳細キー。これ以外は落とす */
const ALLOWED_ERROR_DETAIL_KEYS = new Set([
  "fields", // 400 validation_error
  "items", // 409 out_of_stock
  "amounts", // 409 price_changed
  "order_number", // 409 already_ordered
  "from", // 409 invalid_transition
  "to",
  "field", // 409 duplicate / 422 limit_exceeded
  "limit", // 422
  "message", // 500 internal_error（固定文言）
]);

export interface ApiError {
  code: string;
  [key: string]: unknown;
}

export type ApiResult<T> =
  | { ok: true; status: number; data: T }
  /** `retryAfter` は 429 のとき FastAPI の `Retry-After` ヘッダ（Wave 2 の注文照会が透過する） */
  | { ok: false; status: number; error: ApiError; retryAfter?: string | null };

export class UpstreamUnavailableError extends Error {
  constructor(message: string, readonly reason?: unknown) {
    super(message);
    this.name = "UpstreamUnavailableError";
  }
}

/** FastAPI のエラー本文を `{code, ...}` の形に整形する。code が無い・形が違うものは丸める */
export function sanitizeErrorBody(status: number, body: unknown): ApiError {
  if (typeof body === "object" && body !== null && typeof (body as { code?: unknown }).code === "string") {
    const src = body as Record<string, unknown>;
    const out: ApiError = { code: src.code as string };
    for (const key of Object.keys(src)) {
      if (ALLOWED_ERROR_DETAIL_KEYS.has(key)) out[key] = src[key];
    }
    return out;
  }
  return { code: status >= 500 ? "upstream_error" : "bad_response" };
}

export interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  /** JSON にして送る本文 */
  json?: unknown;
  timeoutMs?: number;
}

/**
 * `path` は `/health` や `/products` のように `/api/v1` 以降を渡す。
 */
export async function apiFetch<T = unknown>(path: string, options: ApiFetchOptions = {}): Promise<ApiResult<T>> {
  const env = getEnv();
  const { json, timeoutMs = DEFAULT_TIMEOUT_MS, headers, ...init } = options;
  const url = `${env.API_BASE_URL}${API_PREFIX}${path.startsWith("/") ? path : `/${path}`}`;

  const reqHeaders = new Headers(headers);
  reqHeaders.set("X-Internal-Token", env.INTERNAL_TOKEN);
  reqHeaders.set("Accept", "application/json");
  if (json !== undefined) reqHeaders.set("Content-Type", "application/json");

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: reqHeaders,
      body: json !== undefined ? JSON.stringify(json) : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (cause) {
    // 接続拒否・DNS 失敗・タイムアウト。詳細はログのみ（利用者にはコードだけ返す）
    console.error("[api] upstream unavailable", {
      path,
      reason: cause instanceof Error ? cause.message : String(cause),
    });
    throw new UpstreamUnavailableError("FastAPI に接続できません", cause);
  }

  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!res.ok) {
    return {
      ok: false,
      status: res.status,
      error: sanitizeErrorBody(res.status, body),
      retryAfter: res.status === 429 ? res.headers.get("Retry-After") : null,
    };
  }
  return { ok: true, status: res.status, data: body as T };
}
