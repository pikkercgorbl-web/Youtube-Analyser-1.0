import { cleanup, render, screen, within } from "@testing-library/react";
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

function link(name: string) {
  return screen.getAllByRole("link", { name })[0]!;
}

describe("Sidebar IA (1.21G)", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders Исследование, Radar, and Система groups", () => {
    render(<Sidebar />);
    expect(screen.getAllByTestId("sidebar-nav-group")).toHaveLength(3);
    expect(screen.getByText("Исследование")).toBeInTheDocument();
    expect(screen.getByText("Radar")).toBeInTheDocument();
    expect(screen.getByText("Система")).toBeInTheDocument();
  });

  it("hides legacy sidebar entries", () => {
    render(<Sidebar />);
    expect(screen.queryByRole("link", { name: "Исследование ниш" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Взрывные каналы" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Сохранённые идеи" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /keyword-analyze/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Поиск видео" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Массовый анализ" })).not.toBeInTheDocument();
  });

  it("shows renamed research items with correct routes", () => {
    render(<Sidebar />);
    expect(link("Ручной поиск")).toHaveAttribute("href", "/");
    expect(link("Анализ конкурентов")).toHaveAttribute("href", "/mass-analysis");
  });

  it("Radar group starts with Возможности then supporting views", () => {
    render(<Sidebar />);
    const radarHeading = screen.getByText("Radar");
    const radarGroup = radarHeading.closest("[data-testid='sidebar-nav-group']");
    expect(radarGroup).not.toBeNull();
    const scope = within(radarGroup as HTMLElement);
    expect(scope.getByRole("link", { name: "Возможности" })).toHaveAttribute("href", "/opportunities");
    expect(scope.getByRole("link", { name: "Пул ключей" })).toHaveAttribute("href", "/keywords");
    expect(scope.getByRole("link", { name: "Производительность ключей" })).toHaveAttribute(
      "href",
      "/keyword-performance",
    );
    expect(scope.getByRole("link", { name: "Мониторинг" })).toHaveAttribute("href", "/monitoring");
  });

  it("Operations is under Система", () => {
    render(<Sidebar />);
    const systemHeading = screen.getByText("Система");
    const systemGroup = systemHeading.closest("[data-testid='sidebar-nav-group']");
    expect(systemGroup).not.toBeNull();
    const scope = within(systemGroup as HTMLElement);
    expect(scope.getByRole("link", { name: "Операции" })).toHaveAttribute("href", "/operations");
    expect(scope.queryByRole("link", { name: "Мониторинг" })).not.toBeInTheDocument();
  });
});
