import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/layout/sidebar";

vi.mock("next/navigation", () => ({
  usePathname: () => "/keywords",
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>,
}));

describe("Sidebar IA (1.21F)", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders conceptual nav groups", () => {
    render(<Sidebar />);
    const groups = screen.getAllByTestId("sidebar-nav-group");
    expect(groups.length).toBe(3);
    expect(screen.getByText("Поиск и ключи")).toBeInTheDocument();
    expect(screen.getByText("Наблюдение")).toBeInTheDocument();
    expect(screen.getByText("Анализ")).toBeInTheDocument();
  });

  it("renames niche research and adds keyword pool", () => {
    render(<Sidebar />);
    expect(screen.getAllByRole("link", { name: "Исследование ниш" })[0]).toHaveAttribute(
      "href",
      "/keyword-research",
    );
    expect(screen.getAllByRole("link", { name: "Пул ключей" })[0]).toHaveAttribute(
      "href",
      "/keywords",
    );
    expect(screen.queryByRole("link", { name: "Ключевые слова" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Производительность ключей" })).toHaveAttribute(
      "href",
      "/keyword-performance",
    );
  });
});
