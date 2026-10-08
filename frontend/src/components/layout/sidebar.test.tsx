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

  it("renders Поиск, Разведка, and Сбор данных groups", () => {
    render(<Sidebar />);
    expect(screen.getAllByTestId("sidebar-nav-group")).toHaveLength(3);
    expect(screen.getByText("Поиск")).toBeInTheDocument();
    expect(screen.getByText("Разведка")).toBeInTheDocument();
    expect(screen.getByText("Сбор данных")).toBeInTheDocument();
  });

  it("hides legacy sidebar entries", () => {
    render(<Sidebar />);
    expect(
      screen.queryByRole("link", { name: "Поиск ниш" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Взрывные каналы" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Сохранённые идеи" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /keyword-analyze/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Поиск видео" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Массовый анализ" }),
    ).not.toBeInTheDocument();
  });

  it("shows renamed research items with correct routes", () => {
    render(<Sidebar />);
    expect(link("Ручной поиск")).toHaveAttribute("href", "/");
    expect(link("Анализ конкурентов")).toHaveAttribute(
      "href",
      "/mass-analysis",
    );
  });

  it("Разведка group starts with Возможности then supporting views", () => {
    render(<Sidebar />);
    const radarHeading = screen.getByText("Поиск");
    const radarGroup = radarHeading.closest(
      "[data-testid='sidebar-nav-group']",
    );
    expect(radarGroup).not.toBeNull();
    const scope = within(radarGroup as HTMLElement);
    expect(link("Возможности")).toHaveAttribute("href", "/opportunities");
    expect(
      scope.getByRole("link", { name: "Поисковые запросы" }),
    ).toHaveAttribute("href", "/keywords");
    expect(
      scope.getByRole("link", { name: "Отдача запросов" }),
    ).toHaveAttribute("href", "/keyword-performance");
    expect(link("Наблюдение за видео")).toHaveAttribute("href", "/monitoring");
  });

  it("Operations is under Сбор данных", () => {
    render(<Sidebar />);
    const systemHeading = screen.getByText("Сбор данных");
    const systemGroup = systemHeading.closest(
      "[data-testid='sidebar-nav-group']",
    );
    expect(systemGroup).not.toBeNull();
    const scope = within(systemGroup as HTMLElement);
    expect(
      scope.getByRole("link", { name: "Состояние системы" }),
    ).toHaveAttribute("href", "/operations");
    expect(
      scope.getByRole("link", { name: "Наблюдение за видео" }),
    ).toBeInTheDocument();
  });
});
