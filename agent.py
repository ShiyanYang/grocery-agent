"""
agent.py - the meal-planning chat with the model, and the shopping list that follows it.

The text rules live in their own modules:
    meal_types.py     which meals the user asked for
    meal_plan.py      finding and checking a plan in a model reply
    shopping_list.py  what to buy once there is a plan
"""
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from mlx_lm import generate, load
from mlx_lm.sample_utils import make_sampler

from config import config
from meal_plan import MealPlan, check_meal_plan
from meal_types import update_requested_meal_types
from memory import Memory
from pantry import list_items
from shopping_list import build_shopping_list

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Your role is to assist the user with meal planning.

CRITICAL INSTRUCTIONS:
1. The first question is always about the number of days for meal planning.
2. You need to understand the user's preferences and dietary restrictions.
3. Plan only the meals the user asks for (breakfast, lunch, dinner, snacks) and do not add extra meals.
4. After each question, your next response is either a follow-up question or the meal plan.
5. The meal plan response must be in JSON format only. It must follow this schema:
'''
[
  {"day": "Day 1", "meal_type": "<a meal the user asked for>", "meal_name": "...", "ingredients": ["...", "..."]},
  {"day": "Day 1", "meal_type": "<a meal the user asked for>", "meal_name": "...", "ingredients": ["...", "..."]}
]
'''
"""

EMPTY_PANTRY_RULE = "6. The user's pantry is empty, so every ingredient will need to be bought."

PANTRY_RULE = """6. The user's pantry already has: {items}.
   Where they fit what the user asked for, build meals that include these items so less needs to be bought.
   You do not need to use every item, and never break the user's wishes or dietary needs to use one.
   Buying ingredients is expected. Each meal must list every ingredient the dish needs, including ones that are not in the pantry, and the ingredients must match the meal name (for example, Lentil Soup needs lentils). Never leave out an ingredient because it is not in the pantry."""

EXIT_WORDS = ("exit", "quit", "bye")


def build_system_prompt(pantry_list: List[str]) -> str:
    """The system prompt, ending with a rule that tells the model what is in the pantry."""
    pantry_items = []
    for item in pantry_list:
        if isinstance(item, str) and item.strip():
            pantry_items.append(item.strip())

    if pantry_items:
        pantry_rule = PANTRY_RULE.format(items=", ".join(pantry_items))
    else:
        pantry_rule = EMPTY_PANTRY_RULE
    return SYSTEM_PROMPT + pantry_rule + "\n"


class Agent:
    """Chats with the user to make a meal plan, then works out the shopping list."""

    _model_cache: Dict[str, Tuple[Any, Any]] = {}

    @classmethod
    def get_model(cls, model_path: str) -> Any:
        """Load a model once per path and reuse it across agent instances."""
        if model_path not in cls._model_cache:
            cls._model_cache[model_path] = load(model_path)
        return cls._model_cache[model_path]

    def __init__(self, model_path: str):
        self.llm, self.tokenizer = self.get_model(model_path)
        self.memory = Memory()

    def generate_text(self, messages: List[Dict[str, str]], temperature: Optional[float] = None,
                      max_tokens: Optional[int] = None) -> str:
        """Generate a response from chat messages using the MLX model."""
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        if temperature is None:
            temperature = config.LLM_TEMPERATURE
        return generate(
            self.llm,
            self.tokenizer,
            prompt=prompt,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS,
            sampler=make_sampler(temp=temperature),
        ).strip()

    def search_pantry(self) -> List[str]:
        """The pantry items on disk, or an empty list if they can't be read."""
        try:
            return list_items() or []
        except Exception as e:
            logger.error(f"Failed to search pantry: {e}")
            return []

    def generate_meal_plan(self, input_fn: Optional[Callable[[str], str]] = None,
                           output_fn: Optional[Callable[[str], None]] = None,
                           pantry_list: Optional[List[str]] = None) -> Optional[MealPlan]:
        """Chat with the user until the model produces a valid meal plan, or the user exits.

        input_fn / output_fn default to the terminal (input / print); the eval
        harness passes scripted versions so a conversation can run without stdin.
        The pantry is shown to the model so it can plan meals that use it.
        If pantry_list is None, the pantry is read from disk.
        """
        input_fn = input_fn or input
        output_fn = output_fn or print
        if pantry_list is None:
            pantry_list = self.search_pantry()

        messages = [{"role": "system", "content": build_system_prompt(pantry_list)}]
        # Meal types the user has named so far. Built from the user's own messages only: repair
        # feedback is also sent as a user message and names the extra meal ("Remove lunch ..."),
        # so reading it would make that meal look requested.
        requested_meal_types: Set[str] = set()

        output_fn("Hi I am your meal planning assistant. How many days do you want to prepare for meals?")
        while True:
            try:
                user_input = input_fn("You: ")
            except EOFError:
                user_input = "exit"
            if user_input.strip().lower() in EXIT_WORDS:
                output_fn("See you next time : )")
                return None

            messages.append({"role": "user", "content": user_input})
            self.memory.add(f"User: {user_input}")
            requested_meal_types = update_requested_meal_types(requested_meal_types, user_input)

            plan = self._reply_with_repairs(messages, requested_meal_types, output_fn)
            if plan is not None:
                output_fn("Meal plan generated.")
                return plan

    def _reply_with_repairs(self, messages: List[Dict[str, str]], requested_meal_types: Set[str],
                            output_fn: Callable[[str], None]) -> Optional[MealPlan]:
        """Get the model's next reply; if it is a plan that breaks a rule, ask the model to fix it.

        Returns the valid plan, or None if the reply was not a plan (e.g. a follow-up question)
        or the plan was still broken after config.MAX_REPAIR_ATTEMPTS fixes.
        """
        content = self._ask(messages, output_fn)
        plan, feedback = check_meal_plan(content, requested_meal_types)

        attempts = 0
        while feedback and attempts < config.MAX_REPAIR_ATTEMPTS:
            attempts += 1
            output_fn(f"Meal plan rejected, asking for a fix "
                      f"(attempt {attempts}/{config.MAX_REPAIR_ATTEMPTS}): {feedback}")
            messages.append({"role": "user", "content": feedback})
            content = self._ask(messages, output_fn)
            plan, feedback = check_meal_plan(content, requested_meal_types)

        if feedback:
            output_fn(f"Could not get a valid meal plan after {attempts} correction attempt(s): {feedback}")
        return plan

    def _ask(self, messages: List[Dict[str, str]], output_fn: Callable[[str], None]) -> str:
        """Generate the assistant's next reply, show it, and record it in history and memory."""
        try:
            content = self.generate_text(messages)
        except (KeyError, IndexError, AttributeError):
            output_fn("MLX model generation is not available")
            raise
        output_fn(f"Answer:{content}")
        messages.append({"role": "assistant", "content": content})
        self.memory.add(f"Assistant: {content}")
        return content

    def generate_shopping_list(self, meal_plan: Optional[MealPlan],
                               pantry_list: Optional[List[str]] = None) -> List[str]:
        """What to buy for the meal plan, leaving out what is already in the pantry.

        If pantry_list is None, the pantry is read from disk.
        """
        if meal_plan is None:
            logger.warning("No meal plan provided")
            return []
        if pantry_list is None:
            pantry_list = self.search_pantry()

        shopping_list = build_shopping_list(meal_plan, pantry_list)
        if shopping_list:
            logger.info(f"Generated shopping list with {len(shopping_list)} items")
        else:
            logger.info("All ingredients available in pantry")
        return shopping_list
