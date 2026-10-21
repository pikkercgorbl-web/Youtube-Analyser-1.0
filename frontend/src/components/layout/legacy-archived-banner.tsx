import Link from "next/link";

import {
  LEGACY_ARCHIVED_BANNER_TITLE,
  type LegacyRouteId,
  legacyArchivedBannerLead,
} from "@/lib/legacy-routes";

export function LegacyArchivedBanner({
  route,
  primaryHref,
  primaryLabel,
}: {
  route: LegacyRouteId;
  primaryHref: string;
  primaryLabel: string;
}) {
  return (
    <div
      className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm"
      role="status"
      data-testid="legacy-archived-banner"
    >
      <p className="font-medium text-foreground">{LEGACY_ARCHIVED_BANNER_TITLE}</p>
      <p className="mt-1 text-muted-foreground">{legacyArchivedBannerLead(route)}</p>
      <Link href={primaryHref} className="mt-2 inline-block font-medium text-primary hover:underline">
        {primaryLabel} →
      </Link>
    </div>
  );
}
