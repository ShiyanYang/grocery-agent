"""
meal_types.py - work out which meals (breakfast, lunch, ...) the user asked for or refused.

Example:
    >>> sorted(find_meal_types("Only breakfast and dinner, no lunch."))
    ['breakfast', 'dinner']
"""
import re
from typing import List, Set, Tuple

# Meal types the agent looks for in what the user says and in a plan's meal_type labels.
MEAL_TYPES = ["breakfast", "brunch", "lunch", "dinner", "snack", "dessert"]

# Other words for a meal type.
MEAL_TYPE_ALIASES = {"supper": "dinner"}

# A meal word right after one of these is refused, not requested: "no lunch", "everything except lunch".
NEGATION_WORDS = ["no", "not", "without", "except", "skip", "minus"]

# The user is replacing the meals they asked for earlier: "Actually, lunch only."
REPLACING_WORDS = ["only", "instead"]

# The user is adding to meals named earlier, possibly by the model: "Yes, and snacks too."
ADDING_WORDS = ["too", "also", "plus", "as well"]


def _contains_word(text: str, words: List[str]) -> bool:
    for word in words:
        if re.search(rf"\b{word}\b", text, re.IGNORECASE):
            return True
    return False


def _is_negated(text: str, position: int) -> bool:
    """True if one of the 3 words before position, in the same clause, is a negation word.

    'everything except lunch' and 'no lunch or dinner' are negated; 'No nuts. Dinner only.' is not.
    """
    clause_start = 0
    for punctuation in re.finditer(r"[.,;!?]", text[:position]):
        clause_start = punctuation.end()
    words_before = re.findall(r"[a-z']+", text[clause_start:position].lower())[-3:]
    for word in words_before:
        if word in NEGATION_WORDS:
            return True
    return False


def _find_meal_words(text: str) -> List[Tuple[str, bool]]:
    """Each meal word in text as (meal type, negated), e.g. 'Supper, no snacks' -> [('dinner', False), ('snack', True)].

    Plurals count ('snacks', 'lunches') and aliases map to their meal type ('supper' -> 'dinner').
    """
    found = []
    for word in MEAL_TYPES + list(MEAL_TYPE_ALIASES):
        meal_type = MEAL_TYPE_ALIASES.get(word, word)
        for match in re.finditer(rf"\b{word}(?:s|es)?\b", text, re.IGNORECASE):
            found.append((meal_type, _is_negated(text, match.start())))
    return found


def find_meal_types(text: str) -> Set[str]:
    """The meal types asked for in text, e.g. 'Only breakfast and dinner, no lunch.' -> {'breakfast', 'dinner'}."""
    found = set()
    for meal_type, negated in _find_meal_words(text):
        if not negated:
            found.add(meal_type)
    return found


def find_refused_meal_types(text: str) -> Set[str]:
    """The meal types refused in text, e.g. 'Everything except lunch.' -> {'lunch'}."""
    found = set()
    for meal_type, negated in _find_meal_words(text):
        if negated:
            found.add(meal_type)
    return found


def update_requested_meal_types(requested: Set[str], user_message: str) -> Set[str]:
    """The meal types plans are checked against after the user sends user_message.

    An empty set means "not sure", and then plans are not checked: a missed extra meal is better
    than rejecting a good plan.
    """
    named = find_meal_types(user_message)
    refused = find_refused_meal_types(user_message)
    if not named and not refused:
        return requested

    if _contains_word(user_message, REPLACING_WORDS):
        earlier = set()
    elif not requested and _contains_word(user_message, ADDING_WORDS):
        # "Yes, and snacks too": added to meals the model offered, which we don't track.
        return set()
    else:
        earlier = requested

    # "Everything except lunch" with nothing known earlier leaves an empty set, so nothing is checked.
    return (earlier | named) - refused


def join_words(words: List[str]) -> str:
    """['lunch'] -> 'lunch'; ['breakfast', 'dinner'] -> 'breakfast and dinner'; three -> 'a, b and c'."""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]
