function parseCommaTokens(value: string): string[] {
  return value
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);
}

/**
 * Build a YouTube search query with native plus/minus operators.
 * Example: "k pop", "tutorial, обзор", "minecraft, free, shorts"
 * → "k pop tutorial обзор -minecraft -free -shorts"
 */
export function buildYouTubeSearchQuery(
  baseQuery: string,
  plusWordsRaw = "",
  minusWordsRaw = "",
): string {
  const parts: string[] = [];
  const base = baseQuery.trim();
  if (base) {
    parts.push(base);
  }

  parts.push(...parseCommaTokens(plusWordsRaw));

  for (const token of parseCommaTokens(minusWordsRaw)) {
    parts.push(token.startsWith("-") ? token : `-${token}`);
  }

  return parts.join(" ").trim();
}
