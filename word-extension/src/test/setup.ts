import { vi } from "vitest";

vi.mock("../services/logger", () => ({
  log: vi.fn(),
  __esModule: true,
}));

(globalThis as any).Office = (globalThis as any).Office ?? {
  context: {},
};
