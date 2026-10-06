"""Conservative multilingual particles used only for Pattern Family comparison.

These tokens rotate in Hindi/English tutorial titles (postpositions / question words)
and make phrase identity overly order-sensitive. They are NOT stripped from stored
pattern labels. Content verbs like ``banaye`` and topical nouns stay.

Do not treat this as a stemmer or translator.
"""

from __future__ import annotations

from app.services.attention_title_normalization import significant_tokens

# Comparison-only. Keep original Pattern.label untouched.
FAMILY_GENERIC_PARTICLES = frozenset(
    {
        "se",
        "kaise",
        "ko",
        "ki",
        "ke",
        "ka",
        "mein",
        "main",
        "hai",
        "hain",
        "aur",
        "kya",
        "ho",
        "tha",
        "thi",
    }
)


def family_content_tokens(label: str) -> frozenset[str]:
    """Order-insensitive content tokens for sibling comparison."""
    tokens = [token for token in significant_tokens(label) if token not in FAMILY_GENERIC_PARTICLES]
    if len(tokens) >= 2:
        return frozenset(tokens)
    return frozenset(significant_tokens(label))
