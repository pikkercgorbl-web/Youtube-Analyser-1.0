"use client";

import { Suspense } from "react";

import { ChannelSingleAnalysisHome } from "@/components/mass-analysis/channel-single-analysis-home";

export default function ChannelSingleAnalysisPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Загрузка…</p>}>
      <ChannelSingleAnalysisHome />
    </Suspense>
  );
}
