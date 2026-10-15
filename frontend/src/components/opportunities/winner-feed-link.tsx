"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import {
  WINNER_FOCUS_HASH_PREFIX,
  winnerFeedHref,
} from "@/lib/opportunity-family-presentation";

export function navigateToWinnerFeedVideo(videoId: string) {
  if (typeof window === "undefined") {
    return;
  }
  const hash = `#${WINNER_FOCUS_HASH_PREFIX}${encodeURIComponent(videoId)}`;
  const onOpportunities =
    window.location.pathname === "/opportunities" ||
    window.location.pathname.endsWith("/opportunities");
  if (!onOpportunities) {
    window.location.href = `/opportunities${hash}`;
    return;
  }
  if (window.location.hash !== hash) {
    window.location.hash = hash;
  }
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export function WinnerFeedLink({
  videoId,
  children,
  className,
}: {
  videoId: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={winnerFeedHref(videoId)}
      className={className}
      onClick={(event) => {
        event.preventDefault();
        navigateToWinnerFeedVideo(videoId);
      }}
    >
      {children}
    </Link>
  );
}
