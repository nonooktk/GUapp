import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FitSummary from "@/components/FitSummary";

// テスト設計書 UT-WEB-24（サイズ感の表示。DS-SCR-003）。設計仕様書 6.6・DS-API-003 fit_summary・DS-DEC-81・AT-17
describe("UT-WEB-24 サイズ感の表示", () => {
  it("total 0: 「サイズ感のレビューはまだありません」（棒・件数は出さない）", () => {
    render(<FitSummary summary={{ total: 0, small: 0, just: 0, large: 0 }} />);
    expect(screen.getByTestId("fit-empty")).toHaveTextContent("サイズ感のレビューはまだありません");
    expect(screen.queryByTestId("fit-bar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("fit-total")).not.toBeInTheDocument();
  });

  it("summary が無い（古い API の応答）ときも 0 件の表示", () => {
    render(<FitSummary summary={undefined} />);
    expect(screen.getByTestId("fit-empty")).toBeInTheDocument();
  });

  it("total 1（just だけ）: 「全 1 件」と件数 3 つ。0 件の区間は幅 0", () => {
    render(<FitSummary summary={{ total: 1, small: 0, just: 1, large: 0 }} />);
    expect(screen.getByTestId("fit-total")).toHaveTextContent("全 1 件");
    expect(screen.getByTestId("fit-small")).toHaveTextContent("小さめ0");
    expect(screen.getByTestId("fit-just")).toHaveTextContent("ちょうどよい1");
    expect(screen.getByTestId("fit-large")).toHaveTextContent("大きめ0");
    const grows = Array.from(screen.getByTestId("fit-bar").children).map((c) => (c as HTMLElement).style.flexGrow);
    expect(grows).toEqual(["0", "1", "0"]);
  });

  it("total 10（2／6／2）: 棒の幅は件数の比（20%／60%／20%、合計 100%）。ラベルの文字が棒の下に出る", () => {
    render(<FitSummary summary={{ total: 10, small: 2, just: 6, large: 2 }} />);
    expect(screen.getByRole("heading", { name: "サイズ感（購入者の声）" })).toBeInTheDocument();
    expect(screen.getByTestId("fit-total")).toHaveTextContent("全 10 件");
    const segs = Array.from(screen.getByTestId("fit-bar").children) as HTMLElement[];
    const counts = segs.map((c) => Number(c.style.flexGrow));
    expect(counts).toEqual([2, 6, 2]);
    const sum = counts.reduce((a, b) => a + b, 0);
    expect(counts.map((n) => (n / sum) * 100)).toEqual([20, 60, 20]);
    // 色だけに頼らず、文字（ラベル＋件数）が出る
    const legend = screen.getByRole("list", { name: "サイズ感の内訳" });
    expect(legend).toHaveTextContent("小さめ");
    expect(legend).toHaveTextContent("ちょうどよい");
    expect(legend).toHaveTextContent("大きめ");
    expect(screen.getByTestId("fit-just")).toHaveTextContent("6");
    // 棒そのものは装飾（スクリーンリーダーには凡例を読ませる）
    expect(screen.getByTestId("fit-bar")).toHaveAttribute("aria-hidden", "true");
  });
});
