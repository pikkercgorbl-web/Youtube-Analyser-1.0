import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SavedResearchAnalystFeedbackPanel } from "./saved-research-analyst-feedback-panel";

const getSavedVideoFeedback = vi.fn();
const postSavedVideoFeedback = vi.fn();

vi.mock("@/lib/api", () => ({
  getSavedVideoFeedback: (...args: unknown[]) => getSavedVideoFeedback(...args),
  postSavedVideoFeedback: (...args: unknown[]) => postSavedVideoFeedback(...args),
  getSavedFamilyFeedback: vi.fn(),
  postSavedFamilyFeedback: vi.fn(),
}));

describe("SavedResearchAnalystFeedbackPanel", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    getSavedVideoFeedback.mockReset();
    postSavedVideoFeedback.mockReset();
  });

  it("shows empty state when no feedback", async () => {
    getSavedVideoFeedback.mockResolvedValue({
      latest: null,
      items: [],
      total: 0,
      limit: 10,
      offset: 0,
    });
    render(<SavedResearchAnalystFeedbackPanel kind="video" entityId={1} archived={false} />);
    expect(await screen.findByText("Оценок пока нет.")).toBeTruthy();
  });

  it("submits feedback and shows success", async () => {
    getSavedVideoFeedback
      .mockResolvedValueOnce({
        latest: null,
        items: [],
        total: 0,
        limit: 10,
        offset: 0,
      })
      .mockResolvedValueOnce({
        latest: {
          id: 2,
          entity_kind: "video",
          entity_id: 1,
          verdict: "USEFUL",
          reason: "note",
          created_at: "2026-10-10T12:00:00Z",
        },
        items: [
          {
            id: 2,
            entity_kind: "video",
            entity_id: 1,
            verdict: "USEFUL",
            reason: "note",
            created_at: "2026-10-10T12:00:00Z",
          },
        ],
        total: 1,
        limit: 10,
        offset: 0,
      });
    postSavedVideoFeedback.mockResolvedValue({});
    render(<SavedResearchAnalystFeedbackPanel kind="video" entityId={1} archived={false} />);
    await screen.findByText("Оценок пока нет.");
    fireEvent.change(screen.getByPlaceholderText("Почему такой вердикт"), {
      target: { value: "note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить оценку" }));
    await waitFor(() => expect(postSavedVideoFeedback).toHaveBeenCalled());
    expect(await screen.findByText("Оценка сохранена")).toBeTruthy();
    expect(await screen.findByText("Текущая оценка:")).toBeTruthy();
  });

  it("shows error on failed submit", async () => {
    getSavedVideoFeedback.mockResolvedValue({
      latest: null,
      items: [],
      total: 0,
      limit: 10,
      offset: 0,
    });
    postSavedVideoFeedback.mockRejectedValue(new Error("network"));
    render(<SavedResearchAnalystFeedbackPanel kind="video" entityId={1} archived={false} />);
    await screen.findByText("Оценок пока нет.");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить оценку" }));
    expect(await screen.findByText("network")).toBeTruthy();
  });

  it("loads more history when paginated", async () => {
    getSavedVideoFeedback
      .mockResolvedValueOnce({
        latest: {
          id: 2,
          entity_kind: "video",
          entity_id: 1,
          verdict: "USEFUL",
          reason: null,
          created_at: "2026-10-10T12:00:00Z",
        },
        items: [
          {
            id: 2,
            entity_kind: "video",
            entity_id: 1,
            verdict: "USEFUL",
            reason: null,
            created_at: "2026-10-10T12:00:00Z",
          },
        ],
        total: 3,
        limit: 10,
        offset: 0,
      })
      .mockResolvedValueOnce({
        latest: {
          id: 2,
          entity_kind: "video",
          entity_id: 1,
          verdict: "USEFUL",
          reason: null,
          created_at: "2026-10-10T12:00:00Z",
        },
        items: [
          {
            id: 1,
            entity_kind: "video",
            entity_id: 1,
            verdict: "NOT_RELEVANT",
            reason: null,
            created_at: "2026-10-09T12:00:00Z",
          },
        ],
        total: 3,
        limit: 10,
        offset: 1,
      });
    render(<SavedResearchAnalystFeedbackPanel kind="video" entityId={1} archived={false} />);
    await screen.findByText("История оценок");
    fireEvent.click(screen.getByRole("button", { name: "Показать ещё" }));
    await waitFor(() => expect(getSavedVideoFeedback).toHaveBeenCalledTimes(2));
    expect(screen.getByText("09.10.2026, 18:00:00")).toBeTruthy();
  });
});
