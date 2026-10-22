import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SavedResearchMetadataForm } from "./saved-research-metadata-form";

describe("SavedResearchMetadataForm status select", () => {
  afterEach(() => cleanup());

  it("uses readable foreground on the closed select control", () => {
    render(
      <SavedResearchMetadataForm
        status="WATCHING"
        notes=""
        tagsText=""
        archivedAt={null}
        saving={false}
        saveMessage={null}
        saveError={null}
        onStatusChange={vi.fn()}
        onNotesChange={vi.fn()}
        onTagsChange={vi.fn()}
        onSave={vi.fn()}
        onArchive={vi.fn()}
        onRestore={vi.fn()}
      />,
    );

    const select = screen.getByLabelText("Статус сохранённого исследования");
    expect(select.className).toMatch(/text-foreground/);
    expect(select.className).toMatch(/bg-background/);
    expect(select.className).not.toMatch(/bg-transparent/);
  });
});
