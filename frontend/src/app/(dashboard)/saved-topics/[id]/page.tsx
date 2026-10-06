import { SavedTopicDetailView } from "@/components/saved-topics/saved-topic-detail";

export default function SavedTopicDetailPage({ params }: { params: { id: string } }) {
  const topicId = Number.parseInt(params.id, 10);
  if (!Number.isFinite(topicId)) {
    return null;
  }
  return <SavedTopicDetailView topicId={topicId} />;
}
