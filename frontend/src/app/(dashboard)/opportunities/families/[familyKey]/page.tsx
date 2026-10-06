import { PatternFamilyDetailView } from "@/components/opportunities/pattern-family-detail";

export default function PatternFamilyDetailPage({
  params,
}: {
  params: { familyKey: string };
}) {
  const familyKey = decodeURIComponent(params.familyKey);
  return <PatternFamilyDetailView familyKey={familyKey} />;
}
