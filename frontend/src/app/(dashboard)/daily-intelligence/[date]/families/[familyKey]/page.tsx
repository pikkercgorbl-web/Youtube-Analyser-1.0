import { DailyIntelligenceFamilyDetailView } from "@/components/daily-intelligence/daily-intelligence-family-detail-view";
import { decodeDailyIntelligenceRouteParam } from "@/lib/daily-intelligence-routes";

export default function DailyIntelligenceFamilyDetailPage({
  params,
}: {
  params: { date: string; familyKey: string };
}) {
  const reportDate = decodeDailyIntelligenceRouteParam(params.date);
  const familyKey = decodeDailyIntelligenceRouteParam(params.familyKey);
  return (
    <DailyIntelligenceFamilyDetailView reportDate={reportDate} familyKey={familyKey} />
  );
}
