"""Tests for the eval harness: dataset loading, scoring, and scripted agent conversations."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import Agent
from eval import DEFAULT_CASES, judge_run, load_cases, parse_judge_reply, score_run

ROOT = Path(__file__).resolve().parent.parent

CASE = {
    "id": "t",
    "turns": ["2 days"],
    "pantry": ["Salt", "rice"],
    "expect": {
        "days": 2,
        "meal_types": ["breakfast", "dinner"],
        "forbidden_ingredients": ["egg", "chicken"],
        "shopping_list_excludes_pantry": True,
    },
}

GOOD_PLAN = [
    {"day": "Day 1", "meal_type": "breakfast", "meal_name": "Oats", "ingredients": ["oats", "milk"]},
    {"day": "Day 1", "meal_type": "dinner", "meal_name": "Ratatouille", "ingredients": ["eggplant", "zucchini", "tomato"]},
    {"day": "Day 2", "meal_type": "Breakfast", "meal_name": "Toast", "ingredients": ["bread"]},
    {"day": "Day 2", "meal_type": "dinner", "meal_name": "Rice bowl", "ingredients": ["rice", "tofu"]},
]


def test_golden_dataset_loads():
    cases = load_cases(str(ROOT / DEFAULT_CASES))
    assert len(cases) >= 5
    for case in cases:
        assert case["turns"], case["id"]


def test_load_cases_rejects_duplicate_ids(tmp_path):
    f = tmp_path / "cases.jsonl"
    f.write_text("\n".join(json.dumps({"id": "a", "turns": ["x"]}) for _ in range(2)))
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(str(f))


def test_score_good_plan_passes():
    result = score_run(CASE, GOOD_PLAN, ["oats", "milk", "tofu"])
    assert result["passed"], result


def test_score_no_plan_fails_every_check():
    result = score_run(CASE, None, [])
    assert not result["passed"]
    assert not any(result["checks"].values())


def test_score_eggplant_is_not_egg_but_eggs_is():
    assert score_run(CASE, GOOD_PLAN, [])["checks"]["forbidden_ingredients"]
    plan = GOOD_PLAN + [{"day": "Day 2", "meal_type": "dinner", "meal_name": "X", "ingredients": ["Eggs"]}]
    result = score_run(CASE, plan, [])
    assert not result["checks"]["forbidden_ingredients"]
    assert result["details"]["forbidden_hits"] == ["Eggs"]


def test_score_detects_wrong_days_and_meal_types():
    plan = [m for m in GOOD_PLAN if m["day"] == "Day 1"] + [
        {"day": "Day 1", "meal_type": "lunch", "meal_name": "Soup", "ingredients": ["broth"]}
    ]
    checks = score_run(CASE, plan, [])["checks"]
    assert not checks["days"]
    assert not checks["meal_types"]


def test_score_detects_pantry_leak():
    result = score_run(CASE, GOOD_PLAN, ["salt "])
    assert not result["checks"]["shopping_list_excludes_pantry"]


def test_meals_with_many_ingredients_are_accepted(agent):
    plan = [_meal(12)]
    with patch.object(agent, "generate_text", return_value=json.dumps(plan)) as gen:
        assert agent.generate_meal_plan(input_fn=lambda _: "1 day", output_fn=lambda _: None) == plan
    assert gen.call_count == 1  # no repair round-trip
    assert "max_ingredients_per_meal" not in score_run({"id": "t", "turns": [], "expect": {}}, plan, [])["checks"]


@pytest.fixture
def agent():
    tokenizer = MagicMock()
    tokenizer.apply_chat_template.return_value = "prompt"
    with patch("agent.load", return_value=(MagicMock(), tokenizer)), patch("agent.Memory"):
        Agent._model_cache.clear()
        yield Agent(model_path="mock/model")
        Agent._model_cache.clear()


def test_generate_meal_plan_runs_on_scripted_input(agent):
    turns = iter(["2 days", "breakfast only"])
    output = []
    replies = ["How many meals a day?", json.dumps(GOOD_PLAN)]
    with patch.object(agent, "generate_text", side_effect=replies):
        plan = agent.generate_meal_plan(input_fn=lambda _: next(turns), output_fn=output.append)
    assert plan == GOOD_PLAN
    assert "Meal plan generated." in output


def test_generate_meal_plan_stops_on_eof(agent):
    def no_stdin(_):
        raise EOFError

    with patch.object(agent, "generate_text") as gen:
        assert agent.generate_meal_plan(input_fn=no_stdin, output_fn=lambda _: None) is None
    gen.assert_not_called()


def test_shopping_list_uses_given_pantry(agent):
    with patch("agent.list_items") as list_items:
        result = agent.generate_shopping_list(GOOD_PLAN, pantry_list=["Milk", "rice"])
    list_items.assert_not_called()
    assert "milk" not in [i.lower() for i in result]
    assert "rice" not in result


def test_score_forbidden_exceptions_allow_qualified_ingredient():
    case = {"id": "gf", "turns": ["x"], "expect": {
        "forbidden_ingredients": ["soy sauce", "bread"],
        "forbidden_exceptions": ["gluten-free", "gluten free"],
    }}
    plan = [{"day": "Day 1", "meal_type": "dinner", "meal_name": "Stir fry",
             "ingredients": ["Gluten-Free Soy Sauce", "gluten free bread", "tofu"]}]
    assert score_run(case, plan, [])["checks"]["forbidden_ingredients"]
    plan[0]["ingredients"].append("soy sauce")
    assert score_run(case, plan, [])["details"]["forbidden_hits"] == ["soy sauce"]


# ============ AGENT SELF-REPAIR ============

def _meal(n_ingredients, name="Stew", day="Day 1"):
    return {"day": day, "meal_type": "dinner", "meal_name": name,
            "ingredients": [f"i{k}" for k in range(n_ingredients)]}


def test_invalid_json_plan_is_sent_back_and_fixed(agent):
    broken = '[{"day": "Day 1", "meal_type": "dinner", "meal_name": "X", "ingredients": ["a",]}]'
    good = json.dumps([_meal(3)])
    replies = iter([broken, good])
    # A copy of the messages the model received on each call. The agent keeps adding to the same
    # list after each call, so the mock's own record would show later messages too.
    seen = []

    def fake_generate(messages):
        seen.append(list(messages))
        return next(replies)

    with patch.object(agent, "generate_text", side_effect=fake_generate):
        plan = agent.generate_meal_plan(input_fn=lambda _: "1 day", output_fn=lambda _: None)
    assert plan == json.loads(good)
    assert len(seen) == 2
    repair_request = seen[1][-1]
    assert repair_request["role"] == "user"
    assert "not valid JSON" in repair_request["content"]


def test_repair_gives_up_after_max_attempts(agent):
    from config import config

    bad = json.dumps([{"day": "Day 1", "meal_type": "dinner"}])  # missing meal_name and ingredients
    turns = iter(["1 day", "exit"])
    output = []
    with patch.object(agent, "generate_text", return_value=bad) as gen:
        plan = agent.generate_meal_plan(input_fn=lambda _: next(turns), output_fn=output.append)
    assert plan is None
    assert gen.call_count == 1 + config.MAX_REPAIR_ATTEMPTS
    assert any(o.startswith("Could not get a valid meal plan") for o in output)


def test_follow_up_question_is_not_treated_as_bad_plan(agent):
    turns = iter(["3 days", "exit"])
    with patch.object(agent, "generate_text", return_value="Any dietary restrictions?") as gen:
        assert agent.generate_meal_plan(input_fn=lambda _: next(turns), output_fn=lambda _: None) is None
    assert gen.call_count == 1


# ============ SCORING ROBUSTNESS ============

def test_score_malformed_meals_fail_instead_of_raising():
    plan = [{"meal_name": "No day or type"}, "not a dict",
            {"day": "Day 1", "meal_type": "dinner", "meal_name": "X", "ingredients": "rice"}]
    result = score_run(CASE, plan, [])
    assert not result["passed"]
    assert not result["checks"]["valid_plan"]
    assert result["details"]["malformed_meals"] == 1


def test_score_pantry_leak_tolerates_plurals_and_qualifiers():
    case = {"id": "p", "turns": ["x"], "pantry": ["egg", "olive oil", "rice", "garlic"],
            "expect": {"shopping_list_excludes_pantry": True}}
    shopping = ["Eggs", "extra virgin olive oil", "rice vinegar", "garlic powder", "tofu"]
    result = score_run(case, GOOD_PLAN, shopping)
    assert result["details"]["pantry_items_in_shopping_list"] == ["Eggs", "extra virgin olive oil"]


def test_score_forbidden_term_in_meal_name_is_caught():
    case = {"id": "v", "turns": ["x"], "expect": {"forbidden_ingredients": ["chicken"]}}
    plan = [{"day": "Day 1", "meal_type": "dinner", "meal_name": "Chicken Curry",
             "ingredients": ["curry paste", "rice"]}]
    assert score_run(case, plan, [])["details"]["forbidden_hits"] == ["Chicken Curry"]


# ============ LLM JUDGE ============

VERDICT = {"diet_compliant": True, "matches_request": True, "coherent": True, "score": 4, "issues": []}


def test_parse_judge_reply_accepts_json_wrapped_in_text():
    verdict = parse_judge_reply("Here is my verdict:\n" + json.dumps(VERDICT) + "\nThanks")
    assert verdict["passed"] and verdict["score"] == 4


def test_parse_judge_reply_fails_on_any_false_field_and_bad_score():
    verdict = parse_judge_reply(json.dumps({**VERDICT, "diet_compliant": False, "score": 9}))
    assert not verdict["passed"]
    assert verdict["score"] is None


def test_parse_judge_reply_reports_garbage():
    assert "error" in parse_judge_reply("I think it's fine")
    assert "error" in parse_judge_reply('{"score": 3}')


def test_judge_run_sends_request_and_plan():
    case = {"id": "j", "turns": ["2 days", "no nuts"], "expect": {"judge_criteria": "Meals must be quick."}}
    seen = []

    def fake_generate(messages):
        seen.append(messages)
        return json.dumps(VERDICT)

    assert judge_run(case, GOOD_PLAN, fake_generate)["passed"]
    user_msg = seen[0][-1]["content"]
    assert "no nuts" in user_msg and "Ratatouille" in user_msg and "Meals must be quick." in user_msg


def test_judge_run_without_plan_fails_without_calling_model():
    gen = MagicMock()
    assert not judge_run(CASE, None, gen)["passed"]
    gen.assert_not_called()


def test_judge_run_captures_generation_errors():
    def boom(_):
        raise RuntimeError("oom")
    assert judge_run(CASE, GOOD_PLAN, boom)["error"] == "RuntimeError: oom"


@pytest.mark.parametrize("shopping_item,pantry_item", [
    ("pepper", "black pepper"),  # generic pepper is a different item from black pepper
    ("oil", "olive oil"),
    ("rice vinegar", "rice"),
])
def test_generic_or_different_items_are_not_pantry_leaks(shopping_item, pantry_item):
    case = {"id": "p", "turns": [], "pantry": [pantry_item], "expect": {"shopping_list_excludes_pantry": True}}
    result = score_run(case, GOOD_PLAN, [shopping_item])
    assert result["checks"]["shopping_list_excludes_pantry"]


# ============ THREE-WAY PANTRY CHECK ============

from eval import _pantry_match


@pytest.mark.parametrize("item,pantry_item,expected", [
    ("chicken breasts", "chicken breast", "leak"),
    ("boneless chicken breasts", "chicken breast", "leak"),
    ("Boneless, Skinless Chicken Breast", "chicken breast", "leak"),
    ("cooked rice", "rice", "leak"),
    ("table salt", "salt", "leak"),
    ("Extra Virgin Olive Oil", "olive oil", "leak"),
    ("fresh chopped onions", "onion", "leak"),
    ("brown rice", "rice", "possible"),
    ("cooked brown rice", "rice", "possible"),
    ("Sweet potatoes", "potatoes", "possible"),
    ("rice vinegar", "rice", None),
    ("garlic powder", "garlic", None),
    ("pepper", "black pepper", None),
    ("eggplant", "egg", None),
])
def test_pantry_match(item, pantry_item, expected):
    assert _pantry_match(item, pantry_item) == expected


def test_possible_pantry_items_are_reported_but_do_not_fail():
    case = {"id": "p", "turns": [], "pantry": ["rice", "chicken breast"],
            "expect": {"shopping_list_excludes_pantry": True}}
    result = score_run(case, GOOD_PLAN, ["brown rice", "tofu"])
    assert result["checks"]["shopping_list_excludes_pantry"]
    assert result["details"]["possible_pantry_items"] == ["brown rice"]
    assert result["details"]["pantry_items_in_shopping_list"] == []

    result = score_run(case, GOOD_PLAN, ["brown rice", "boneless chicken breasts"])
    assert not result["checks"]["shopping_list_excludes_pantry"]
    assert result["details"]["pantry_items_in_shopping_list"] == ["boneless chicken breasts"]


def test_parse_judge_reply_ignores_gemma_thinking():
    reply = ('<|channel>thought\nThe user said {"no nuts"}. Checking...\n<channel|>'
             + json.dumps(VERDICT))
    verdict = parse_judge_reply(reply)
    assert verdict["passed"] and verdict["score"] == 4
