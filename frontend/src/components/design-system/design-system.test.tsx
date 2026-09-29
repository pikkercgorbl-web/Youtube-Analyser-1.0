import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  CheckpointBadge,
  CheckpointBadgeFromVideo,
  CycleStatusBadge,
  EvidenceBadge,
  LifecycleBadge,
  SystemStatusBadge,
} from "@/components/design-system/status-badges";
import { SummaryStrip } from "@/components/design-system/summary-strip";
import { EmptyState, ZeroContextNote } from "@/components/design-system/states";
import { InfoTooltip } from "@/components/design-system/info-tooltip";
import {
  checkpointStatusLabel,
  cycleStatusLabel,
  evidenceStatusLabel,
  lifecycleLabel,
} from "@/lib/design-system/labels";
import { formatRelativeFromReference } from "@/components/design-system/freshness";

describe("design-system labels", () => {
  it("translates lifecycle without raw enum in UI label", () => {
    expect(lifecycleLabel("probation")).toBe("Пробный");
    expect(lifecycleLabel("active")).toBe("В работе");
    expect(lifecycleLabel("unknown_x")).toBe("unknown_x");
  });

  it("translates evidence statuses", () => {
    expect(evidenceStatusLabel("insufficient")).toBe("Мало данных");
    expect(evidenceStatusLabel("established")).toBe("Есть исходы 72 ч");
  });

  it("translates checkpoint and cycle", () => {
    expect(checkpointStatusLabel("overdue")).toBe("Просрочено");
    expect(cycleStatusLabel("ok")).toBe("Успешно");
  });
});

describe("status badges", () => {
  it("LifecycleBadge shows Russian text", () => {
    render(<LifecycleBadge status="probation" />);
    expect(screen.getByText("Пробный")).toBeInTheDocument();
    expect(screen.queryByText("probation")).not.toBeInTheDocument();
  });

  it("EvidenceBadge separates from lifecycle visually by label", () => {
    render(<EvidenceBadge status="early" />);
    expect(screen.getByText("Ранняя стадия")).toBeInTheDocument();
  });

  it("CheckpointBadge uses Russian overdue label", () => {
    render(<CheckpointBadge status="overdue" />);
    expect(screen.getByText("Просрочено")).toBeInTheDocument();
  });

  it("CheckpointBadgeFromVideo respects item prop and due checkpoints", () => {
    render(
      <CheckpointBadgeFromVideo
        item={{
          monitoring_status: "active",
          due_checkpoint_hours: [12],
          overdue_checkpoint_hours: [],
        }}
      />,
    );
    expect(screen.getByText("Пора снять снимок")).toBeInTheDocument();
  });

  it("SystemStatusBadge maps activity states", () => {
    render(<SystemStatusBadge state="stale_activity" />);
    expect(screen.getByText("Давно не было циклов")).toBeInTheDocument();
  });

  it("CycleStatusBadge does not show raw ok in visible text", () => {
    render(<CycleStatusBadge status="ok" />);
    expect(screen.getByText("Успешно")).toBeInTheDocument();
  });
});

describe("SummaryStrip", () => {
  it("renders lines and details action", () => {
    const onDetails = vi.fn();
    render(
      <SummaryStrip
        tone="warning"
        lines={[{ text: "Discovery не запускался 11 дней", emphasis: true }]}
        onDetails={onDetails}
      />,
    );
    expect(screen.getByText(/Discovery не запускался/)).toBeInTheDocument();
    screen.getByRole("button", { name: "Подробнее" }).click();
    expect(onDetails).toHaveBeenCalled();
  });
});

describe("states", () => {
  it("empty vs unavailable copy", () => {
    render(<EmptyState title="Нет данных" description="Очередь пуста" compact />);
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();

    render(<EmptyState title="Недоступно" variant="unavailable" compact />);
    expect(screen.getAllByTestId("empty-state").length).toBe(2);
  });

  it("zero context is distinct from empty state", () => {
    render(<ZeroContextNote>0 eligible — нет кандидатов под правила</ZeroContextNote>);
    expect(screen.getByTestId("zero-context")).toHaveTextContent("0 eligible");
  });
});

describe("InfoTooltip", () => {
  it("exposes title for short help", () => {
    render(<InfoTooltip content="Просмотров в час" />);
    expect(screen.getByRole("button", { name: "Подсказка" })).toHaveAttribute(
      "title",
      "Просмотров в час",
    );
  });
});

describe("freshness", () => {
  it("never semantics when iso missing", () => {
    expect(formatRelativeFromReference(null, "2026-01-01T12:00:00Z").never).toBe(true);
    expect(formatRelativeFromReference(null, "2026-01-01T12:00:00Z").relative).toBe("никогда");
  });
});
