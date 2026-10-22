import { Skeleton } from "@/components/ui/skeleton";
import { PageShell } from "@/components/design-system";
import { surfaces } from "@/lib/design-system/layout";
import { cn } from "@/lib/utils";

export function OpportunityWinnerDetailSkeleton() {
  return (
    <div data-testid="winner-detail-skeleton">
    <PageShell>
      <Skeleton className="mb-4 h-9 w-40" />
      <article className={cn(surfaces.section, "overflow-hidden rounded-2xl")}>
        <Skeleton className="aspect-video w-full rounded-none" />
        <div className="space-y-4 p-5 md:p-6">
          <Skeleton className="h-8 w-full max-w-xl" />
          <Skeleton className="h-4 w-64" />
          <div className="grid grid-cols-2 gap-4 border-y border-border/60 py-4 sm:max-w-md">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
          <Skeleton className="h-3 w-full max-w-2xl" />
          <div className="grid gap-2 sm:grid-cols-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        </div>
      </article>
    </PageShell>
    </div>
  );
}
