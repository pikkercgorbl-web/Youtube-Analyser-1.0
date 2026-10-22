"use client";

import { Disclosure } from "@/components/design-system";

export function DailyIntelligenceFrozenJson({
  label,
  payload,
}: {
  label: string;
  payload: Record<string, unknown>;
}) {
  if (!payload || Object.keys(payload).length === 0) {
    return null;
  }
  return (
    <Disclosure summary={label}>
      <pre
        className="max-h-96 overflow-auto rounded-lg border border-border bg-muted/20 p-3 text-xs font-mono whitespace-pre-wrap break-all"
        data-testid="di-frozen-json"
      >
        {JSON.stringify(payload, null, 2)}
      </pre>
    </Disclosure>
  );
}
