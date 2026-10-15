"use client";

import { useParams } from "next/navigation";

import { SavedVideoDetailView } from "@/components/saved-research/saved-video-detail-view";

export default function SavedVideoDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  if (!Number.isFinite(id)) {
    return null;
  }
  return <SavedVideoDetailView videoId={id} />;
}
