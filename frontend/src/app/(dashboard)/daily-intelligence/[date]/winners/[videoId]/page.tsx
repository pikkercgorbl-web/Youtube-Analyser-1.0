import { DailyIntelligenceWinnerDetailView } from "@/components/daily-intelligence/daily-intelligence-winner-detail-view";
import { decodeDailyIntelligenceRouteParam } from "@/lib/daily-intelligence-routes";

export default function DailyIntelligenceWinnerDetailPage({
  params,
}: {
  params: { date: string; videoId: string };
}) {
  const reportDate = decodeDailyIntelligenceRouteParam(params.date);
  const videoId = decodeDailyIntelligenceRouteParam(params.videoId);
  return (
    <DailyIntelligenceWinnerDetailView reportDate={reportDate} videoId={videoId} />
  );
}
