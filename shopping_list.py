"""
shopping_list.py - turn a meal plan into the list of things to buy.

Every ingredient in the plan is listed once, leaving out what is already in the pantry.
"""
from typing import List, Optional

from ingredient_match import normalize, pantry_match
from meal_plan import MealPlan


def build_shopping_list(meal_plan: MealPlan, pantry_list: Optional[List[str]]) -> List[str]:
    """The plan's ingredients, without duplicates and without items already in the pantry.

    Uses the same rules as the eval (ingredient_match.py): 'chicken breasts' and
    'boneless chicken breast' are left out for pantry 'chicken breast'; 'brown rice' is kept
    for pantry 'rice' because it may be a different item.
    """
    if not isinstance(meal_plan, list):
        raise TypeError(f"Expected list, got {type(meal_plan).__name__}")

    pantry_items = []
    for item in pantry_list or []:
        if isinstance(item, str) and item.strip():
            pantry_items.append(item)

    shopping_list = []
    seen = set()
    for ingredient in _all_ingredients(meal_plan):
        if not isinstance(ingredient, str):
            continue
        normalized = normalize(ingredient)
        if normalized in seen:
            continue
        seen.add(normalized)

        if not _in_pantry(ingredient, pantry_items):
            shopping_list.append(ingredient)

    return shopping_list


def _all_ingredients(meal_plan: MealPlan) -> List[str]:
    """Every ingredient entry in the plan, in order, duplicates included."""
    ingredients = []
    for meal in meal_plan:
        meal_ingredients = meal.get("ingredients", [])
        if isinstance(meal_ingredients, list):
            ingredients.extend(meal_ingredients)
    return ingredients


def _in_pantry(ingredient: str, pantry_items: List[str]) -> bool:
    for pantry_item in pantry_items:
        if pantry_match(ingredient, pantry_item) == "leak":
            return True
    return False
