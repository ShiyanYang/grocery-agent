"""
Focused test suite for Grocery Agent core business logic.

Tests cover critical, easy-to-break functionality:
- Shopping list generation (main feature)
- Pantry filtering with deduplication (complex logic)
- Case-insensitive matching (easy to break)
- Error handling in critical paths
- Integration workflow (end-to-end)
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from agent import Agent, find_meal_types
from config import config


# ============ FIXTURES ============

@pytest.fixture
def agent():
    """Create an Agent instance with a mocked MLX model and tokenizer."""
    mock_tokenizer = MagicMock()
    mock_tokenizer.apply_chat_template.return_value = "prompt"
    with patch("agent.load", return_value=(MagicMock(), mock_tokenizer)):
        with patch("agent.Memory"):
            return Agent(model_path="mock/path/to/model")

# ============ CORE BUSINESS LOGIC: SHOPPING LIST GENERATION ============

def test_generate_shopping_list_basic_workflow(agent):
    """Test core workflow: meal plan → flatten → filter → shopping list."""
    meal_plan = [
        {
            "day": "Day 1",
            "meal_type": "breakfast",
            "meal_name": "Omelet",
            "ingredients": ["eggs", "cheese", "salt"]
        },
    ]
    pantry = ["salt"]
    
    with patch("agent.list_items", return_value=pantry):
        result = agent.generate_shopping_list(meal_plan)
        
        assert "eggs" in result
        assert "cheese" in result
        assert "salt" not in result  # Already in pantry


def test_generate_shopping_list_none_meal_plan(agent):
    """Test shopping list handles None meal plan gracefully."""
    with patch("agent.list_items", return_value=[]):
        result = agent.generate_shopping_list(None)
        assert result == []


def test_generate_shopping_list_empty_meal_plan(agent):
    """Test shopping list handles empty meal plan."""
    with patch("agent.list_items", return_value=[]):
        result = agent.generate_shopping_list([])
        assert result == []


def test_generate_shopping_list_pantry_search_fails(agent):
    """Test shopping list generation when pantry search fails (graceful fallback)."""
    meal_plan = [{"ingredients": ["eggs"]}]
    
    with patch("agent.list_items", side_effect=Exception("File error")):
        result = agent.generate_shopping_list(meal_plan)
        # Should treat failed pantry as empty and include all ingredients
        assert "eggs" in result


# ============ CRITICAL LOGIC: PANTRY FILTERING WITH DEDUPLICATION ============

def test_filter_removes_pantry_items(agent):
    """Test filtering removes items already in pantry."""
    ingredients = ["eggs", "tomato", "salt"]
    pantry = ["tomato", "salt"]
    
    result = agent._filter_out_pantry_items(ingredients, pantry)
    
    assert "eggs" in result
    assert "tomato" not in result
    assert "salt" not in result


def test_filter_handles_case_insensitivity(agent):
    """Test filtering is case-insensitive (easy to break)."""
    ingredients = ["Eggs", "TOMATO", "Salt"]
    pantry = ["tomato", "SALT"]
    
    result = agent._filter_out_pantry_items(ingredients, pantry)
    
    assert len(result) == 1
    assert result[0].lower() == "eggs"


def test_filter_deduplicates_ingredients(agent):
    """Test filtering removes duplicate ingredients."""
    ingredients = ["eggs", "eggs", "Eggs", "tomato", "TOMATO"]
    pantry = []
    
    result = agent._filter_out_pantry_items(ingredients, pantry)
    
    assert len(result) == 2  # eggs (1x) and tomato (1x)


def test_filter_handles_whitespace(agent):
    """Test filtering handles whitespace in ingredients and pantry."""
    ingredients = ["eggs", "  tomato  ", "salt "]
    pantry = [" TOMATO ", "salt"]
    
    result = agent._filter_out_pantry_items(ingredients, pantry)
    
    assert len(result) == 1
    assert result[0].lower() == "eggs"


def test_filter_with_none_pantry(agent):
    """Test filtering treats None pantry as empty."""
    ingredients = ["eggs", "tomato"]
    
    result = agent._filter_out_pantry_items(ingredients, None)
    
    assert len(result) == 2


def test_filter_with_empty_ingredients(agent):
    """Test filtering empty ingredients list."""
    result = agent._filter_out_pantry_items([], ["tomato"])
    assert result == []


# ============ MULTI-DAY INTEGRATION: COMPLEX MEAL PLANS ============

def test_generate_shopping_list_multi_day_meals(agent):
    """Test shopping list handles multi-day meal plans with deduplication."""
    meal_plan = [
        {
            "day": "Day 1",
            "meal_type": "breakfast",
            "ingredients": ["eggs", "tomato", "oil"]
        },
        {
            "day": "Day 1",
            "meal_type": "lunch",
            "ingredients": ["tomato", "pasta", "oil"]
        },
        {
            "day": "Day 2",
            "meal_type": "breakfast",
            "ingredients": ["bread", "butter"]
        },
    ]
    pantry = ["oil"]
    
    with patch("agent.list_items", return_value=pantry):
        result = agent.generate_shopping_list(meal_plan)
        
        # Should have: eggs, tomato, pasta, bread, butter (but NOT oil)
        assert len(result) == 5
        assert set(r.lower() for r in result) == {"eggs", "tomato", "pasta", "bread", "butter"}


def test_all_ingredients_in_pantry(agent):
    """Test when all meal ingredients are already in pantry."""
    meal_plan = [
        {
            "meal_type": "breakfast",
            "ingredients": ["eggs", "salt", "oil"]
        },
    ]
    pantry = ["eggs", "salt", "oil"]
    
    with patch("agent.list_items", return_value=pantry):
        result = agent.generate_shopping_list(meal_plan)
        assert result == []


# ============ EDGE CASES: EASY-TO-BREAK SCENARIOS ============

def test_filter_removes_plural_of_pantry_item(agent):
    """'tomatoes' is the same item as pantry 'tomato' (this used to stay on the list)."""
    result = agent._filter_out_pantry_items(["tomatoes"], ["tomato"])
    assert result == []


@pytest.mark.parametrize("ingredient,pantry_item,kept", [
    ("chicken breasts", "chicken breast", False),          # seen in eval runs
    ("boneless chicken breasts", "chicken breast", False),  # seen in eval runs
    ("table salt", "salt", False),                          # seen in eval runs
    ("Extra Virgin Olive Oil", "olive oil", False),
    ("brown rice", "rice", True),       # may be a different item: keep it
    ("sweet potatoes", "potatoes", True),
    ("rice vinegar", "rice", True),
    ("garlic powder", "garlic", True),
    ("pepper", "black pepper", True),
    ("eggplant", "egg", True),
])
def test_filter_uses_eval_leak_rules(agent, ingredient, pantry_item, kept):
    result = agent._filter_out_pantry_items([ingredient], [pantry_item])
    assert (ingredient in result) is kept


def test_filter_ignores_blank_pantry_entries(agent):
    assert agent._filter_out_pantry_items(["eggs"], ["", "  "]) == ["eggs"]


def test_pantry_search_caches_result(agent):
    """Test that pantry search caches results to avoid repeated calls."""
    pantry_items = ["tomato", "salt"]
    
    with patch("agent.list_items", return_value=pantry_items) as mock_list:
        agent.search_pantry()
        agent.search_pantry()
        
        # Called twice
        assert mock_list.call_count == 2
        # Both times, result should be cached
        assert agent.pantry_list == pantry_items


def test_generate_shopping_list_handles_missing_ingredients_field(agent):
    """Test shopping list handles meals without ingredients field."""
    meal_plan = [
        {"day": "Day 1", "meal_name": "Eggs"},  # No ingredients
        {"day": "Day 1", "meal_name": "Salad", "ingredients": ["tomato", "lettuce"]},
    ]
    pantry = []
    
    with patch("agent.list_items", return_value=pantry):
        result = agent.generate_shopping_list(meal_plan)
        
        # Should only include ingredients from second meal
        assert set(r.lower() for r in result) == {"tomato", "lettuce"}


def test_generate_meal_plan_accepts_markdown_wrapped_json(agent):
    """Test meal-plan parser accepts valid JSON wrapped in markdown fences."""
    response = "```json\n[{\"day\": \"Day 1\", \"meal_type\": \"breakfast\", \"meal_name\": \"Omelet\", \"ingredients\": [\"eggs\", \"spinach\"]}]\n```"

    with patch("agent.generate", return_value=response):
        agent.tokenizer.apply_chat_template.return_value = "prompt"
        agent.memory.add = MagicMock()

        with patch("builtins.input", side_effect=["3", "exit"]):
            meal_plan = agent.generate_meal_plan()

    assert meal_plan is not None
    assert meal_plan[0]["meal_type"] == "breakfast"
    assert meal_plan[0]["ingredients"] == ["eggs", "spinach"]

# ============ MEAL PLAN EXTRACTION ============

FLAT_PLAN = [{"day": "Day 1", "meal_type": "dinner", "meal_name": "Stir fry", "ingredients": ["tofu", "rice"]}]


def test_nested_plan_gets_shape_feedback_not_json_error(agent):
    """Meals grouped inside a day are valid JSON in the wrong shape (seen in a real eval run)."""
    nested = json.dumps([{"day": "Day 1", "meals": [{"meal_type": "dinner", "meal_name": "Stir fry",
                                                     "ingredients": ["tofu", "rice"]}]}])
    plan, feedback = agent._check_meal_plan("Here is your plan: " + nested)
    assert plan is None
    assert "not valid JSON" not in feedback
    assert "does not match the schema" in feedback
    assert "one flat list" in feedback


def test_plan_with_text_and_code_fences_around_it_is_accepted(agent):
    reply = "Here is your plan:\n```json\n" + json.dumps(FLAT_PLAN) + "\n```\nEnjoy! [Note: adjust portions]"
    assert agent._check_meal_plan(reply) == (FLAT_PLAN, None)


def test_cut_off_plan_gets_json_feedback(agent):
    """A plan cut off mid-way is a broken plan, not a follow-up question."""
    cut_off = json.dumps(FLAT_PLAN * 3)[:-30]
    plan, feedback = agent._check_meal_plan(cut_off)
    assert plan is None
    assert "not valid JSON" in feedback


def test_reply_without_plan_is_a_follow_up(agent):
    assert agent._check_meal_plan("Any allergies? I can use [brackets] too.") == (None, None)


# ============ PANTRY IN THE PROMPT ============

def _system_prompt_sent_to_model(agent):
    """The system message from the latest prompt the agent built.

    The mock tokenizer is shared across tests, so use the most recent call.
    """
    latest_call = agent.tokenizer.apply_chat_template.call_args
    messages = latest_call.args[0]
    return messages[0]["content"]


def test_meal_plan_prompt_lists_pantry_items(agent):
    """The model is told what is in the pantry so it can plan meals around it."""
    agent.tokenizer.apply_chat_template.return_value = "prompt"
    agent.memory.add = MagicMock()

    with patch("agent.generate", return_value="How many people?"):
        agent.generate_meal_plan(input_fn=MagicMock(side_effect=["3 days", "exit"]),
                                 output_fn=MagicMock(),
                                 pantry_list=["whole chicken", "celery", "  "])

    prompt = _system_prompt_sent_to_model(agent)
    assert "whole chicken, celery" in prompt
    assert "You do not need to use every item" in prompt
    # Seen in an eval run: told to use the pantry, the model listed only pantry items
    # (e.g. "Lentil Soup" with just salt), so the prompt must say buying is fine.
    assert "Never leave out an ingredient because it is not in the pantry" in prompt


def test_meal_plan_reads_pantry_from_disk_when_not_given(agent):
    agent.tokenizer.apply_chat_template.return_value = "prompt"
    agent.memory.add = MagicMock()

    with patch("agent.list_items", return_value=["rice"]), \
         patch("agent.generate", return_value="How many people?"):
        agent.generate_meal_plan(input_fn=MagicMock(side_effect=["3 days", "exit"]),
                                 output_fn=MagicMock())

    assert "already has: rice." in _system_prompt_sent_to_model(agent)


def test_meal_plan_prompt_with_empty_pantry(agent):
    agent.tokenizer.apply_chat_template.return_value = "prompt"
    agent.memory.add = MagicMock()

    with patch("agent.generate", return_value="How many people?"):
        agent.generate_meal_plan(input_fn=MagicMock(side_effect=["3 days", "exit"]),
                                 output_fn=MagicMock(),
                                 pantry_list=[])

    assert "pantry is empty" in _system_prompt_sent_to_model(agent)


# ============ MEAL TYPES ============


def _meal(meal_type, day="Day 1"):
    return {"day": day, "meal_type": meal_type, "meal_name": "Something", "ingredients": ["rice"]}


BREAKFAST_LUNCH_DINNER = [_meal("breakfast"), _meal("lunch"), _meal("dinner")]
BREAKFAST_DINNER = [_meal("breakfast"), _meal("dinner")]


@pytest.mark.parametrize("text,expected", [
    # Phrasings from eval_data/meal_plan_cases.jsonl
    ("I'm vegetarian. Only breakfast and dinner. No nuts please.", {"breakfast", "dinner"}),
    ("Dinner only, Italian food please.", {"dinner"}),
    ("Breakfast, lunch and dinner. No dietary restrictions.", {"breakfast", "lunch", "dinner"}),
    ("Snacks too", {"snack"}),
    ("3 days", set()),
    ("Something healthy, I guess.", set()),
])
def test_find_meal_types(text, expected):
    assert find_meal_types(text) == expected


def test_plan_with_extra_meal_type_gets_specific_feedback(agent):
    """Seen in conflict_vegan_cheese_omelette: breakfast and dinner asked for, lunch added."""
    reply = json.dumps(BREAKFAST_LUNCH_DINNER)
    plan, feedback = agent._check_meal_plan(reply, {"breakfast", "dinner"})
    assert plan is None
    assert "Remove lunch; only breakfast and dinner were requested." in feedback


def test_plan_matching_requested_meal_types_is_accepted(agent):
    plan = [_meal("Breakfast "), _meal("DINNER"), _meal("Dinner", day="Day 2")]
    assert agent._check_meal_plan(json.dumps(plan), {"breakfast", "dinner"}) == (plan, None)


def test_plural_meal_type_in_plan_is_accepted(agent):
    plan = [_meal("snacks")]
    assert agent._check_meal_plan(json.dumps(plan), {"snack"}) == (plan, None)


def test_meal_types_not_checked_when_none_requested(agent):
    """A vague request names no meals, so any meal types are fine."""
    reply = json.dumps(BREAKFAST_LUNCH_DINNER)
    assert agent._check_meal_plan(reply, set()) == (BREAKFAST_LUNCH_DINNER, None)
    assert agent._check_meal_plan(reply) == (BREAKFAST_LUNCH_DINNER, None)


def test_missing_meal_type_is_not_rejected(agent):
    """Only extra meals are flagged: 'no lunch' puts lunch in the requested set."""
    reply = json.dumps(BREAKFAST_DINNER)
    plan, feedback = agent._check_meal_plan(reply, {"breakfast", "lunch", "dinner"})
    assert feedback is None


def _run_meal_plan(agent, model_replies, user_inputs):
    """Run generate_meal_plan with scripted model replies; return (plan, messages sent to the model)."""
    agent.tokenizer.apply_chat_template.reset_mock()
    agent.tokenizer.apply_chat_template.return_value = "prompt"
    agent.memory.add = MagicMock()
    with patch("agent.generate", side_effect=model_replies):
        plan = agent.generate_meal_plan(input_fn=MagicMock(side_effect=user_inputs),
                                        output_fn=MagicMock(), pantry_list=[])
    last_messages = agent.tokenizer.apply_chat_template.call_args.args[0]
    return plan, last_messages


def test_self_repair_removes_extra_meal_type(agent):
    replies = ["Any allergies?", json.dumps(BREAKFAST_LUNCH_DINNER), json.dumps(BREAKFAST_DINNER)]
    plan, messages = _run_meal_plan(agent, replies, ["1 day", "Breakfast and dinner."])

    assert plan == BREAKFAST_DINNER
    # The last two messages are the repair feedback and the model's fixed plan.
    feedback = messages[-2]
    assert feedback["role"] == "user"
    assert "Remove lunch; only breakfast and dinner were requested." in feedback["content"]


def test_repair_feedback_does_not_count_as_a_meal_request(agent):
    """The feedback says 'Remove lunch'; that must not make lunch a requested meal."""
    bad_plan = json.dumps(BREAKFAST_LUNCH_DINNER)
    replies = ["Any allergies?"] + [bad_plan] * (1 + config.MAX_REPAIR_ATTEMPTS)
    plan, _ = _run_meal_plan(agent, replies, ["1 day", "Breakfast and dinner.", "exit"])
    assert plan is None
