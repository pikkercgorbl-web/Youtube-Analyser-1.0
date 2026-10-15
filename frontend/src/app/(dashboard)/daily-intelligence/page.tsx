import { Suspense } from "react";

import { LoadingState } from "@/components/design-system";
import { DailyIntelligenceDashboard } from "@/components/daily-intelligence/daily-intelligence-dashboard";

export default function DailyIntelligencePage() {
  return (
    <Suspense fallback={<LoadingState title="Загрузка…" />}>
      <DailyIntelligenceDashboard />
    </Suspense>
  );
}
