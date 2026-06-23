import { Skeleton } from "@/components/ui/skeleton";
import { Card } from "@/components/ui/card";

export function TrendsTableSkeleton() {
  return (
    <Card className="overflow-hidden">
      <div className="space-y-3 p-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    </Card>
  );
}
