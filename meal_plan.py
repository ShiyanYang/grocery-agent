"""
meal_plan.py - find a meal plan in a model reply and check it follows the rules.

check_meal_plan returns feedback the agent sends back to the model when a plan breaks a rule,
so the model can fix it.
"""
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from jsonschema import ValidationError, validate

from meal_types import find_meal_types, join_words

# A meal plan: one dict per meal with "day", "meal_type", "meal_name" and "ingredients".
MealPlan = List[Dict[str, Any]]

MEAL_PLAN_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "day": {"type": "string"},
            "meal_type": {"type": "string"},
            "meal_name": {"type": "string"},
            "ingredients": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["day", "meal_type", "meal_name", "ingredients"],
    },
}

# Added to every repair message sent back to the model.
RESEND_PLAN = "Resend the complete meal plan as JSON only, following the schema."

# Added when a plan has the wrong shape, e.g. meals grouped inside each day.
PLAN_SHAPE_HELP = (
    "Use one flat list with one object per meal, each with day, meal_type, meal_name and ingredients, "
    'for example: [{"day": "Day 1", "meal_type": "breakfast", "meal_name": "Oatmeal", "ingredients": ["oats", "milk"]}, '
    '{"day": "Day 1", "meal_type": "dinner", "meal_name": "Stir fry", "ingredients": ["tofu", "rice"]}]. '
    "Do not group meals inside a day."
)


def check_meal_plan(content: str, requested_meal_types: Optional[Set[str]] = None
                    ) -> Tuple[Optional[MealPlan], Optional[str]]:
    """Extract and validate a meal plan from a model reply.

    If requested_meal_types is given, a plan with any other meal type is rejected.
    Returns one of:
        (plan, None)      the reply contains a valid plan
        (None, feedback)  the reply contains a plan that breaks a rule; feedback says what to fix
        (None, None)      the reply contains no plan, e.g. the model asked a follow-up question
    """
    start = re.search(r'\[\s*\{', content)  # where a list of objects begins
    if start is None:
        return None, None

    try:
        # Read one complete JSON value from the "[" onwards. Nested lists stay whole, and any
        # text after the plan is ignored.
        plan, _ = json.JSONDecoder().raw_decode(content, start.start())
    except json.JSONDecodeError as e:
        return None, f"Your meal plan is not valid JSON ({e}). {RESEND_PLAN}"

    try:
        validate(instance=plan, schema=MEAL_PLAN_SCHEMA)
    except ValidationError as e:
        return None, (f"Your meal plan does not match the schema ({e.message}). "
                      f"{PLAN_SHAPE_HELP} {RESEND_PLAN}")

    # With nothing requested (e.g. a vague request) there is nothing to check.
    if requested_meal_types:
        extras = extra_meal_types(plan, requested_meal_types)
        if extras:
            return None, (f"Remove {join_words(extras)}; I asked only for "
                          f"{join_words(sorted(requested_meal_types))}. {RESEND_PLAN}")

    return plan, None


def extra_meal_types(plan: MealPlan, requested_meal_types: Set[str]) -> List[str]:
    """Meal types in the plan that the user did not ask for, sorted.

    A label counts as the meal types named inside it: 'Afternoon Snack' is a snack, 'Supper' is dinner.
    A label that names no known meal type, like 'Meal 2', is never flagged. Only extra meals are
    checked, not missing ones: spotting what the user wants from their words is not reliable enough
    to demand a meal.
    """
    extras = set()
    for meal in plan:
        label_meal_types = find_meal_types(meal["meal_type"])
        if not label_meal_types:
            continue
        if label_meal_types & requested_meal_types:
            continue
        extras.update(label_meal_types)
    return sorted(extras)
