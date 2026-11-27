
from mlx_lm import generate, load
from mlx_lm.sample_utils import make_sampler
from pantry import list_items
from ingredient_match import pantry_match
from memory import Memory
from config import config
import json
import re
import logging
from typing import Callable, Optional, Dict, List, Any, Set, Tuple
from jsonschema import validate, ValidationError

logger = logging.getLogger(__name__)

# A meal plan: one dict per meal with "day", "meal_type", "meal_name" and "ingredients".
MealPlan = List[Dict[str, Any]]

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


def _join_words(words: List[str]) -> str:
    """['lunch'] -> 'lunch'; ['breakfast', 'dinner'] -> 'breakfast and dinner'; three -> 'a, b and c'."""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]

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
    
        
    def _pantry_instruction(self, pantry_list: List[str]) -> str:
        """The system-prompt rule that tells the model what is already in the pantry."""
        pantry_items = []
        for item in pantry_list:
            if isinstance(item, str) and item.strip():
                pantry_items.append(item.strip())

        if not pantry_items:
            return "5. The user's pantry is empty, so every ingredient will need to be bought."

        return (
            f"5. The user's pantry already has: {', '.join(pantry_items)}.\n"
            "        Where they fit what the user asked for, build meals include these items so less needs "
            "to be bought.\n"
            "        You do not need to use every item, and never break the user's wishes or dietary "
            "needs to use one.\n"
            "        Buying ingredients is expected. Each meal must list every ingredient the dish needs, "
            "including ones that are not in the pantry, and the ingredients must match the meal name "
            "(for example, Lentil Soup needs lentils). Never leave out an ingredient because it is not "
            "in the pantry."
        )

    def generate_meal_plan(self, input_fn: Optional[Callable[[str], str]] = None,
                           output_fn: Optional[Callable[[str], None]] = None,
                           pantry_list: Optional[List[str]] = None) -> Optional[MealPlan]:
        """Generate the meal plan over the next X days.

        input_fn / output_fn default to the terminal (input / print); the eval
        harness passes scripted versions so a conversation can run without stdin.
        The pantry is shown to the model so it can plan meals that use it.
        If pantry_list is None, the pantry is read from disk.
        """
        input_fn = input_fn or input
        output_fn = output_fn or print
        if pantry_list is None:
            pantry_list = self.search_pantry()

        system_prompt = """Your role is to assist the user with meal planning.

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
        """ + self._pantry_instruction(pantry_list) + "\n"

        output_fn("Hi I am your meal planning assistant. How many days do you want to prepare for meals?")
        meal_plan = None

        messages = [
            {"role":"system", "content": system_prompt}
            ]
        # Meal types the user has named so far. Built from the user's own messages only: repair
        # feedback is also sent as a user message and names the extra meal ("Remove lunch ..."),
        # so reading it would make that meal look requested.
        requested_meal_types = set()

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
            requested_meal_types = update_requested_meal_types(requested_meal_types, user_input)

            content = self._ask(messages, output_fn)
            plan, feedback = self._check_meal_plan(content, requested_meal_types)

            # The model attempted a plan but broke a rule: tell it what was wrong and let it retry.
            attempts = 0
            while feedback and attempts < config.MAX_REPAIR_ATTEMPTS:
                attempts += 1
                output_fn(f"Meal plan rejected, asking for a fix "
                          f"(attempt {attempts}/{config.MAX_REPAIR_ATTEMPTS}): {feedback}")
                messages.append({"role": "user", "content": feedback})
                content = self._ask(messages, output_fn)
                plan, feedback = self._check_meal_plan(content, requested_meal_types)

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

    def _check_meal_plan(self, content: str, requested_meal_types: Optional[Set[str]] = None
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
            extra_meal_types = self._extra_meal_types(plan, requested_meal_types)
            if extra_meal_types:
                return None, (f"Remove {_join_words(extra_meal_types)}; I asked only for "
                              f"{_join_words(sorted(requested_meal_types))}. {RESEND_PLAN}")

        return plan, None

    def _extra_meal_types(self, plan: MealPlan, requested_meal_types: Set[str]) -> List[str]:
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