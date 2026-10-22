export type OpportunitiesSection = "videos" | "channels" | "families";

export function parseOpportunitiesSectionFromHash(hash: string): OpportunitiesSection | null {
  const raw = hash.replace(/^#/, "").trim();
  if (!raw) {
    return null;
  }
  if (raw === "section=channels" || raw === "channels") {
    return "channels";
  }
  if (raw === "section=families" || raw === "families") {
    return "families";
  }
  if (raw === "section=videos" || raw === "videos") {
    return "videos";
  }
  return null;
}
