import { describe, expect, it } from "vitest";

import {
  POOL_LIFECYCLE_HELP,
  poolLifecycleLabel,
  poolSourceLabel,
} from "./keyword-pool-copy";

describe("keyword-pool-copy", () => {
  it("uses scheduling lifecycle labels in Russian", () => {
    expect(poolLifecycleLabel("probation")).toBe("Пробный");
    expect(poolLifecycleLabel("active")).toBe("Активный");
    expect(poolLifecycleLabel("weak")).toBe("Редкий");
    expect(poolLifecycleLabel("archived")).toBe("Архив");
  });

  it("translates source types without raw enum in label", () => {
    expect(poolSourceLabel("seed")).toBe("Исходный");
    expect(poolSourceLabel("suggestion")).toBe("Подсказка");
    expect(poolSourceLabel("related")).toBe("Связанный");
    expect(poolSourceLabel("channel")).toBe("Из канала");
    expect(poolSourceLabel("manual")).toBe("Добавлен вручную");
  });

  it("lifecycle help states operational not quality", () => {
    expect(POOL_LIFECYCLE_HELP).toMatch(/не оценка качества/i);
  });
});
