import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// ホーム DS-SCR-001 のトップ画像（U-01）。背景に AI 生成の秋の画像を敷き、既存の文言とリンク先は変えない。
vi.mock("@/lib/server/catalog", () => ({
  getImageBaseUrl: () => "",
  getProducts: async () => ({ items: [], total: 0, page: 1, per_page: 8 }),
  loadOrNull: async (p: Promise<unknown>) => p,
}));
vi.mock("@/lib/server/contents", () => ({
  getContents: async () => ({ items: [] }),
}));

import HomePage from "@/app/page";

describe("ホームのトップ画像", () => {
  it("背景画像（装飾の img・先読み）と、既存の文言・リンク先が出る", async () => {
    render(await HomePage());
    const hero = screen.getByRole("region", { name: "特集" });

    const img = hero.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toBe("/hero/autumn-b.jpg");
    expect(img?.getAttribute("alt")).toBe("");
    expect(img?.getAttribute("fetchpriority")).toBe("high");

    expect(hero.textContent).toContain("2026 AUTUMN");
    expect(hero.textContent).toContain("NEW ARRIVALS");
    expect(screen.getByRole("link", { name: "すべての商品を見る" }).getAttribute("href")).toBe("/products");
  });
});
