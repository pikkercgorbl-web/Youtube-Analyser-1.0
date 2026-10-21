import { Suspense } from "react";

import { LoadingState } from "@/components/design-system";
import { ValidationReportView } from "@/components/validation/validation-report-view";

export default function ValidationPage() {
  return (
    <Suspense fallback={<LoadingState title="Загрузка…" />}>
      <ValidationReportView />
    </Suspense>
  );
}
