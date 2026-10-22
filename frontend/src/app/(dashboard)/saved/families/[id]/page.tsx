"use client";

import { useParams } from "next/navigation";

import { SavedFamilyDetailView } from "@/components/saved-research/saved-family-detail-view";

export default function SavedFamilyDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  if (!Number.isFinite(id)) {
    return null;
  }
  return <SavedFamilyDetailView familyId={id} />;
}
