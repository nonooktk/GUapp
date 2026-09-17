import { describe, expect, it } from "vitest";
import { sanitizeErrorBody } from "@/lib/server/api";

// 設計仕様書 4.5・7.2: FastAPI の応答本文をそのまま返さず `{code, ...}` の形だけ通す
describe("BFF sanitizeErrorBody", () => {
  it("code と許可した詳細キーだけを通す", () => {
    const out = sanitizeErrorBody(409, {
      code: "out_of_stock",
      items: [{ variant_id: 1 }],
      detail: "SQL: SELECT ...", // 通してはいけない
      stack: "Traceback", // 通してはいけない
    });
    expect(out).toEqual({ code: "out_of_stock", items: [{ variant_id: 1 }] });
  });

  it("code が無い本文（FastAPI 既定の {detail} など）は丸める", () => {
    expect(sanitizeErrorBody(500, { detail: "Internal Server Error" })).toEqual({ code: "upstream_error" });
    expect(sanitizeErrorBody(404, { detail: "Not Found" })).toEqual({ code: "bad_response" });
    expect(sanitizeErrorBody(502, null)).toEqual({ code: "upstream_error" });
  });
});
