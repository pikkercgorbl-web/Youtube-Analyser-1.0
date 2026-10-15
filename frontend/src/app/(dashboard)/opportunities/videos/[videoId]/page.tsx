import { OpportunityWinnerDetailView } from "@/components/opportunities/opportunity-winner-detail-view";

export default function OpportunityWinnerDetailPage({
  params,
}: {
  params: { videoId: string };
}) {
  const videoId = decodeURIComponent(params.videoId);
  return <OpportunityWinnerDetailView videoId={videoId} />;
}
