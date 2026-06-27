/** Split comma-separated tokens and trim whitespace. */
function parseCommaTokens(value: string): string[] {
  return value
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);
}

/**
 * Build a YouTube search query with native plus/minus operators.
 * Example: "роблокс", plus "кликер", minus "стрим, шортс" → "роблокс кликер -стрим -шортс".
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

  for (const token of parseCommaTokens(plusWordsRaw)) {
    parts.push(token);
  }

  for (const token of parseCommaTokens(minusWordsRaw)) {
    const normalized = token.startsWith("-") ? token : `-${token}`;
    parts.push(normalized);
  }

  return parts.join(" ").trim();
}
