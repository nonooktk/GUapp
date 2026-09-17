import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// `globals: false` のため Testing Library の自動 cleanup が効かない。各テスト後に DOM を破棄する
afterEach(() => {
  cleanup();
});
