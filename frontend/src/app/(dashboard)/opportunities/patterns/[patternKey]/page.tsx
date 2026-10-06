import { PatternDetailView } from "@/components/opportunities/pattern-detail";

export default function PatternDetailPage({
  params,
}: {
  params: { patternKey: string };
}) {
  const patternKey = decodeURIComponent(params.patternKey);
  return <PatternDetailView patternKey={patternKey} />;
}
