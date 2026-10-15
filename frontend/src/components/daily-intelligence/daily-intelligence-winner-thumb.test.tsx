import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DailyIntelligenceWinnerThumb } from "./daily-intelligence-winner-thumb";

describe("DailyIntelligenceWinnerThumb", () => {
  afterEach(() => cleanup());

  it("renders thumbnail link with mqdefault src", () => {
    render(
      <DailyIntelligenceWinnerThumb
        videoId="dQw4w9WgXcQ"
        title="Test"
        href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
      />,
    );
    const link = screen.getByRole("link", { name: /Открыть на YouTube/i });
    expect(link).toHaveAttribute("href", "https://www.youtube.com/watch?v=dQw4w9WgXcQ");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    const img = link.querySelector("img");
    expect(img).toBeTruthy();
    expect(img?.getAttribute("src")).toContain("i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg");
    expect(img?.getAttribute("loading")).toBe("lazy");
  });

  it("shows fallback for invalid video id", () => {
    render(
      <DailyIntelligenceWinnerThumb
        videoId="not-valid"
        title="Test"
        href="https://www.youtube.com/watch?v=not-valid"
      />,
    );
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("Нет превью")).toBeTruthy();
  });

  it("shows fallback after image error", () => {
    render(
      <DailyIntelligenceWinnerThumb
        videoId="dQw4w9WgXcQ"
        title="Test"
        href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
      />,
    );
    const img = screen.getByRole("link").querySelector("img")!;
    fireEvent.error(img);
    expect(screen.getByText("Нет превью")).toBeTruthy();
  });
});
