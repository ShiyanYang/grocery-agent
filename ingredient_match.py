"""
ingredient_match.py - decide whether a shopping-list entry is something already in the pantry.

Shared by the agent (to filter the shopping list) and the eval (to check it), so both use the
same rules.

Example:
    >>> pantry_match("boneless chicken breasts", "chicken breast")
    'leak'
    >>> pantry_match("brown rice", "rice")
    'possible'
    >>> pantry_match("rice vinegar", "rice") is None
    True
"""
import re
from typing import Any, Optional

# Words that describe an item without changing what it is: "boneless chicken breast" is still
# chicken breast. Words NOT listed here are treated as possibly changing the item ("brown rice"):
# the agent keeps those entries on the shopping list, and the eval lists them for review.
# Add a word here once you've decided it never changes the item.
# TODO: these words may not be comprehensive; consider using a lemmatizer or a more sophisticated NLP approach.
SAME_ITEM_QUALIFIERS = {
    "fresh", "chopped", "boneless", "skinless", "large", "organic", "extra virgin",
    "cooked", "table",
}


def normalize(s: Any) -> str:
    return str(s).strip().lower()


def term_pattern(term: str) -> str:
    """Regex for a whole-word term with an optional plural: 'egg' matches 'eggs' but not 'eggplant'."""
    return r"\b" + re.escape(normalize(term)) + r"(e?s)?\b"


def pantry_match(item: str, pantry_item: str) -> Optional[str]:
    """Compare one shopping-list entry with one pantry item.

    Returns "leak" when the entry is the pantry item (allowing plurals and SAME_ITEM_QUALIFIERS):
    'eggs' ~ 'egg', 'boneless chicken breasts' ~ 'chicken breast'.
    Returns "possible" when the pantry item ends the entry but other words come first:
    'brown rice' ~ 'rice', 'sweet potatoes' ~ 'potatoes'.
    Returns None when it is a different item: 'rice vinegar' ~ 'rice', 'pepper' ~ 'black pepper'.
    """
    match = re.search(term_pattern(pantry_item) + r"$", normalize(item))
    if match is None:
        return None

    leading_words = normalize(item)[:match.start()]
    for qualifier in sorted(SAME_ITEM_QUALIFIERS, key=len, reverse=True):  # "extra virgin" first
        leading_words = re.sub(r"\b" + re.escape(qualifier) + r"\b", " ", leading_words)
    leading_words = re.sub(r"[^a-z]+", " ", leading_words).strip()

    if leading_words:
        return "possible"
    return "leak"
