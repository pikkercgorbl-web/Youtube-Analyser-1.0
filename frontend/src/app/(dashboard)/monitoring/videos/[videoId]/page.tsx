import { MonitoringVideoDetailView } from "@/components/monitoring/monitoring-video-detail";

export default function MonitoringVideoDetailPage({
  params,
}: {
  params: { videoId: string };
}) {
  return <MonitoringVideoDetailView videoId={params.videoId} />;
}
