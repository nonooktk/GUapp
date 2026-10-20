import { describe, expect, it } from "vitest";
import { parseIsoDate, parseOrderQuery } from "@/lib/admin-query";

// テスト設計書 UT-WEB-46（注文一覧の検索条件。DS-SCR-015-3）

describe("UT-WEB-46 注文一覧の検索条件", () => {
  it("既定: すべて・1 ページ目・エラーなし。FastAPI へは page だけ渡す", () => {
    const q = parseOrderQuery({});
    expect(q.errors).toEqual({});
    expect(q.apiQuery).toBe("page=1");
    expect(q.values).toMatchObject({ status: "all", receive_method: "all", from: "", to: "", order_number: "", email: "" });
  });

  it("正常な条件は FastAPI のクエリとリンクに載る（注文番号は大文字、メールは小文字に直す）", () => {
    const q = parseOrderQuery({
      status: "shipped",
      receive_method: "store",
      from: "2026-10-01",
      to: "2026-10-31",
      order_number: " gu-261024-abcdefgh ",
      email: " Test@Example.com ",
      page: "2",
    });
    expect(q.errors).toEqual({});
    const sp = new URLSearchParams(q.apiQuery!);
    expect(Object.fromEntries(sp)).toEqual({
      status: "shipped",
      receive_method: "store",
      from: "2026-10-01",
      to: "2026-10-31",
      order_number: "GU-261024-ABCDEFGH",
      email: "test@example.com",
      page: "2",
    });
    expect(q.linkParams).toEqual({
      status: "shipped",
      receive_method: "store",
      from: "2026-10-01",
      to: "2026-10-31",
      order_number: "GU-261024-ABCDEFGH",
      email: "test@example.com",
    });
  });

  it("状態・受け取り方法の列挙外は既定に戻す", () => {
    const q = parseOrderQuery({ status: "refunded", receive_method: "drone" });
    expect(q.values.status).toBe("all");
    expect(q.values.receive_method).toBe("all");
    expect(q.apiQuery).toBe("page=1");
  });

  it("状態は API の 8 値すべてを受ける", () => {
    for (const s of ["pending_payment", "accepted", "preparing", "shipped", "delivered", "pickup_expired", "cancelled", "payment_failed"]) {
      expect(parseOrderQuery({ status: s }).values.status).toBe(s);
    }
  });

  it.each([["2026-02-30"], ["2026-13-01"], ["2026/10/01"], ["26-10-01"], ["2026-1-1"], ["abc"], ["2026-10-01T00:00"]])(
    "日付が実在しない・形が違う %j はエラーにして FastAPI を呼ばない（入力は戻す）",
    (bad) => {
      const q = parseOrderQuery({ from: bad });
      expect(q.errors.from).toBeTruthy();
      expect(q.apiQuery).toBeNull();
      expect(q.values.from).toBe(bad);
      expect(q.linkParams.from).toBeUndefined();
    },
  );

  it("うるう日は実在する日付として通す", () => {
    expect(parseIsoDate("2028-02-29")).not.toBeNull();
    expect(parseIsoDate("2026-02-29")).toBeNull();
  });

  it("期間が逆順（from > to）なら終了日の項目にエラー。同日は通す", () => {
    const rev = parseOrderQuery({ from: "2026-10-31", to: "2026-10-01" });
    expect(rev.errors.to).toBe("期間の開始日は終了日以前にしてください");
    expect(rev.apiQuery).toBeNull();
    const same = parseOrderQuery({ from: "2026-10-01", to: "2026-10-01" });
    expect(same.errors).toEqual({});
    expect(same.apiQuery).not.toBeNull();
  });

  it("片方だけの期間でもよい", () => {
    expect(parseOrderQuery({ from: "2026-10-01" }).apiQuery).toContain("from=2026-10-01");
    expect(parseOrderQuery({ to: "2026-10-01" }).apiQuery).toContain("to=2026-10-01");
  });

  it.each([["GU-26102-ABCDEFGH"], ["GU-261024-ABCDEFG0"], ["GU-261024-ABCDEFGI"], ["XX-261024-ABCDEFGH"], ["GU-261024-ABCDEFGHI"], ["注文"]])(
    "形が違う注文番号 %j は FastAPI に渡さずエラー（0・1・I・O は注文番号に使わない文字）",
    (bad) => {
      const q = parseOrderQuery({ order_number: bad });
      expect(q.errors.order_number).toBeTruthy();
      expect(q.apiQuery).toBeNull();
    },
  );

  it("メールが 255 文字・空白入り・@ なしならエラー。254 文字ちょうどは通す", () => {
    const local = "a".repeat(254 - "@x.jp".length);
    expect(parseOrderQuery({ email: `${local}@x.jp` }).errors).toEqual({});
    const tooLong = parseOrderQuery({ email: `${local}a@x.jp` });
    expect(tooLong.errors.email).toBeTruthy();
    expect(tooLong.apiQuery).toBeNull();
    expect(parseOrderQuery({ email: "a b@example.com" }).errors.email).toBeTruthy();
    expect(parseOrderQuery({ email: "no-at-sign" }).errors.email).toBeTruthy();
  });

  it("エラーがあっても、ほかの項目の入力は values に残る（直して再検索できる）", () => {
    const q = parseOrderQuery({ from: "bad", email: "a@example.com", status: "shipped" });
    expect(q.values.email).toBe("a@example.com");
    expect(q.values.status).toBe("shipped");
  });

  it("SQL や HTML を含む検索語は FastAPI に渡さない（形式エラー）", () => {
    expect(parseOrderQuery({ order_number: "' OR 1=1 --" }).apiQuery).toBeNull();
    expect(parseOrderQuery({ email: "\"><img src=x onerror=alert(1)>@x.jp" }).errors.email).toBeTruthy();
  });

  it("極端に長い値は読み込まず、戻す値も切る", () => {
    const q = parseOrderQuery({ email: "a".repeat(5000) });
    expect(q.values.email.length).toBeLessThanOrEqual(300);
    expect(q.errors.email).toBeTruthy();
  });

  it("配列で渡された値は先頭の 1 つだけ使う。page は 1 以上の整数以外なら 1", () => {
    expect(parseOrderQuery({ status: ["shipped", "delivered"] }).values.status).toBe("shipped");
    expect(parseOrderQuery({ page: "0" }).page).toBe(1);
    expect(parseOrderQuery({ page: "abc" }).page).toBe(1);
  });
});
