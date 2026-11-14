
from mlx_lm import generate, load
from mlx_lm.sample_utils import make_sampler
from pantry import list_items
from ingredient_match import pantry_match
from memory import Memory
from config import config
import json
import re
import logging
from typing import Callable, Optional, Dict, List, Any, Tuple
from jsonschema import validate, ValidationError

logger = logging.getLogger(__name__)

# A meal plan: one dict per meal with "day", "meal_type", "meal_name" and "ingredients".
MealPlan = List[Dict[str, Any]]

# Added to every repair message sent back to the model.
RESEND_PLAN = "Resend the complete meal plan as JSON only, following the schema."

# Added when a plan has the wrong shape, e.g. meals grouped inside each day.
PLAN_SHAPE_HELP = (
    "Use one flat list with one object per meal, each with day, meal_type, meal_name and ingredients, "
    'for example: [{"day": "Day 1", "meal_type": "breakfast", "meal_name": "Oatmeal", "ingredients": ["oats", "milk"]}, '
    '{"day": "Day 1", "meal_type": "dinner", "meal_name": "Stir fry", "ingredients": ["tofu", "rice"]}]. '
    "Do not group meals inside a day."
)

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
                        "items": {"type": "string"}
                    }
                },
                "required": ["day", "meal_type", "meal_name", "ingredients"]
                }
            }

class Agent:
    """AI agent generates the shopping list."""

    _model_cache: Dict[str, Tuple[Any, Any]] = {}

    @classmethod
    def get_model(cls, model_path: str) -> Any:
        """Load a model once per path and reuse it across agent instances."""
        if model_path not in cls._model_cache:
            cls._model_cache[model_path] = load(model_path)
        return cls._model_cache[model_path]

    def __init__(self, model_path: str):
        """Initialize the agent with model and configuration."""
        self.llm, self.tokenizer = self.get_model(model_path)
        self.pantry_list = None
        self.memory = Memory()
        self.tools = [{
                "type": "function",
                "function": {
                    "name": "update_shopping_list",
                    "description": "Add missing grocery items to the shopping list",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "new_items": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of missing ingredients/items"
                            }
                        },
                        "required": ["new_items"]
                    }
                }
            }]

    def generate_text(self, messages: List[Dict[str, str]], temperature: Optional[float] = None,
                      max_tokens: Optional[int] = None) -> str:
        """Generate a response from chat messages using the MLX model."""
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        sampler = make_sampler(temp = config.LLM_TEMPERATURE if temperature is None else temperature)
        return generate(
            self.llm,
            self.tokenizer,
            prompt=prompt,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS,
            sampler=sampler,
        ).strip()
        
    def search_pantry(self) -> Optional[List[str]]:
        """Search and cache pantry items."""
        try:
            items = list_items()
            self.pantry_list = items if items else []
            return self.pantry_list
        except Exception as e:
            logger.error(f"Failed to search pantry: {e}")
            return []
    
        
    def generate_meal_plan(self, input_fn: Optional[Callable[[str], str]] = None,
                           output_fn: Optional[Callable[[str], None]] = None) -> Optional[MealPlan]:
        """Generate the meal plan over the next X days.

        input_fn / output_fn default to the terminal (input / print); the eval
        harness passes scripted versions so a conversation can run without stdin.
        """
        input_fn = input_fn or input
        output_fn = output_fn or print
        
        system_prompt = """Your role is to assist the user with meal planning.

        CRITICAL INSTRUCTIONS:
        1. The first question is always about the number of days for meal planning.
        2. You need to understand the user's needs.
        3. After each question, your next response is either a follow-up question or the meal plan.
        4. The meal plan response must be in JSON format only. It must follow this schema:
    '''
    [
      {"day": "Day 1", "meal_type": "breakfast", "meal_name": "...", "ingredients": ["...", "..."]},
      {"day": "Day 1", "meal_type": "lunch", "meal_name": "...", "ingredients": ["...", "..."]}
    ]
    '''
        """

        output_fn("Hi I am your meal planning assistant. How many days do you want to prepare for meals?")
        meal_plan = None

        messages = [
            {"role":"system", "content": system_prompt}
            ]
         
        while True:  
            try:
                user_input = input_fn("You: ")
            except EOFError:
                user_input = "exit"
            if user_input.strip().lower() in ('exit','quit','bye'):
                output_fn("See you next time : )")
                break
            
            messages.append({"role":"user","content": user_input})
            # Save user input to persistent memory
            self.memory.add(f"User: {user_input}")
            
            content = self._ask(messages, output_fn)
            plan, feedback = self._check_meal_plan(content)

            # The model attempted a plan but broke a rule: tell it what was wrong and let it retry.
            attempts = 0
            while feedback and attempts < config.MAX_REPAIR_ATTEMPTS:
                attempts += 1
                output_fn(f"Meal plan rejected, asking for a fix "
                          f"(attempt {attempts}/{config.MAX_REPAIR_ATTEMPTS}): {feedback}")
                messages.append({"role": "user", "content": feedback})
                content = self._ask(messages, output_fn)
                plan, feedback = self._check_meal_plan(content)

            if plan is not None:
                meal_plan = plan
                output_fn("Meal plan generated.")
                break
            if feedback:
                output_fn(f"Could not get a valid meal plan after {attempts} correction attempt(s): {feedback}")

        return meal_plan
    
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

    def _check_meal_plan(self, content: str) -> Tuple[Optional[MealPlan], Optional[str]]:
        """Extract and validate a meal plan from a model reply.

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

        return plan, None

    def _normalize(self, item: str) -> str:
        """Lowercase and strip whitespace/punctuation so 'Tomato', 'tomato ', 'Tomatoes' compare cleanly."""
        if not isinstance(item, str):
            raise TypeError(f"Expected string, got {type(item).__name__}")
        return item.strip().lower()

    def _flatten_ingredients(self, meal_plan: MealPlan) -> List[str]:
        """Turn the meal plan into a flat list of ingredient entries."""
        if not isinstance(meal_plan, list):
            raise TypeError(f"Expected list, got {type(meal_plan).__name__}")
        
        all_ingredients = []
        for meal in meal_plan:
            ingredients = meal.get("ingredients", [])
            if isinstance(ingredients, list):
                all_ingredients.extend(ingredients)
        return all_ingredients
    
    def _filter_out_pantry_items(self, ingredients: List[str], pantry_list: Optional[List[str]]) -> List[str]:
        """Remove ingredient entries that are already available in the pantry, and duplicates.

        Uses the same rules as the eval (ingredient_match.py): 'chicken breasts' and
        'boneless chicken breast' are removed for pantry 'chicken breast'; 'brown rice' is kept
        for pantry 'rice' because it may be a different item.
        """
        if not isinstance(ingredients, list):
            raise TypeError(f"Expected list, got {type(ingredients).__name__}")

        pantry_items = [item for item in pantry_list or [] if isinstance(item, str) and item.strip()]

        filtered_ingredients = []
        seen = set()
        for entry in ingredients:
            if not isinstance(entry, str):
                continue
            normalized = self._normalize(entry)
            if normalized in seen:
                continue
            seen.add(normalized)

            in_pantry = False
            for pantry_item in pantry_items:
                if pantry_match(entry, pantry_item) == "leak":
                    in_pantry = True
                    break
            if not in_pantry:
                filtered_ingredients.append(entry)

        return filtered_ingredients

        
    def generate_shopping_list(self, meal_plan: Optional[MealPlan],
                               pantry_list: Optional[List[str]] = None) -> List[str]:
        """Generate the shopping list that is not in the pantry.

        If pantry_list is None, the pantry is read from disk.
        """
        if meal_plan is None:
            logger.warning("No meal plan provided")
            return []
        
        try:
            all_ingredients = self._flatten_ingredients(meal_plan)
            if pantry_list is None:
                pantry_list = self.search_pantry()
            needed = self._filter_out_pantry_items(all_ingredients, pantry_list)
            
            if not needed:
                logger.info("All ingredients available in pantry")
                return []
            
            logger.info(f"Generated shopping list with {len(needed)} items")
            return needed
        except Exception as e:
            logger.error(f"Failed to generate shopping list: {e}")
            raise