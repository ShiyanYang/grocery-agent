#!/usr/bin/env python3
"""
eval.py - run the Agent against a golden dataset of scripted conversations and score the results.

Each case in the dataset (JSONL, one case per line) holds:
  id      - unique name
  turns   - the user messages fed to the agent, in order ("exit" is sent once they run out)
  pantry  - pantry contents used for the shopping list
  expect  - properties the meal plan / shopping list must satisfy (all optional):
              days                          number of distinct days in the plan
              meal_types                    exact set of meal types expected
              max_ingredients_per_meal      upper bound on ingredients per meal
              forbidden_ingredients         terms that must not appear in any ingredient
              forbidden_exceptions          phrases that exempt an ingredient from that check
                                            (e.g. "gluten-free" so "gluten-free soy sauce" is allowed)
              shopping_list_excludes_pantry no pantry item may appear in the shopping list
              judge_criteria                extra instructions for the LLM judge (only used with --judge-model)

Each case is run --repeats times, each run in its own process with a timeout.

Rule checks are deterministic. With --judge-model, an LLM additionally grades each plan for
things rules can't see (implied ingredients such as "pasta" under a gluten-free request,
whether meals make sense, whether the plan matches what the user asked for). Judge verdicts are
reported separately from the rule-based pass/fail.
"""
import argparse
import json
import multiprocessing as mp
import re
import tempfile
import time
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Dict, List, Optional
from agent import Agent
from memory import Memory
from config import config

DEFAULT_CASES = "eval_data/meal_plan_cases.jsonl"


# ============ DATASET ============

def load_cases(path: str) -> List[Dict[str, Any]]:
    cases = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            for key in ("id", "turns"):
                if key not in case:
                    raise ValueError(f"{path}:{lineno}: case missing '{key}'")
            case.setdefault("pantry", [])
            case.setdefault("expect", {})
            cases.append(case)
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate case ids")
    return cases


# ============ SCORING ============

def _norm(s: Any) -> str:
    return str(s).strip().lower()


def _term_pattern(term: str) -> str:
    return r"\b" + re.escape(_norm(term)) + r"(e?s)?\b"


def _contains_term(ingredient: str, term: str) -> bool:
    """Whole-word match allowing a plural suffix, so 'egg' matches 'eggs' but not 'eggplant'."""
    return re.search(_term_pattern(term), _norm(ingredient)) is not None


def _is_pantry_item(item: str, pantry_item: str) -> bool:
    """True when a shopping-list entry is the pantry item, allowing plurals and leading qualifiers.

    'eggs' ~ 'egg' and 'extra virgin olive oil' ~ 'olive oil' match; 'rice vinegar' ~ 'rice'
    and 'garlic powder' ~ 'garlic' do not, because the pantry item must be the final noun phrase.
    """
    return re.search(_term_pattern(pantry_item) + r"$", _norm(item)) is not None


def _meals(meal_plan: Any) -> List[Dict[str, Any]]:
    """Keep only well-formed meal dicts, coercing ingredients to a list of strings."""
    if not isinstance(meal_plan, list):
        return []
    meals = []
    for m in meal_plan:
        if not isinstance(m, dict):
            continue
        ingredients = m.get("ingredients")
        ingredients = [str(i) for i in ingredients] if isinstance(ingredients, list) else []
        meals.append({**m, "ingredients": ingredients})
    return meals


def _check_day_count(meals: List[Dict[str, Any]], expected_days: int):
    """Count distinct day labels ('Day 1', 'day 1 ' count as the same day)."""
    distinct_days = set()
    for meal in meals:
        day = meal.get("day")
        if day:
            distinct_days.add(_norm(day))
    passed = len(distinct_days) == expected_days
    return passed, len(distinct_days)


def _check_meal_types(meals: List[Dict[str, Any]], expected_types: List[str]):
    """The set of meal types in the plan must equal the expected set exactly."""
    found_types = set()
    for meal in meals:
        meal_type = meal.get("meal_type")
        if meal_type:
            found_types.add(_norm(meal_type))

    wanted_types = set()
    for meal_type in expected_types:
        wanted_types.add(_norm(meal_type))

    passed = found_types == wanted_types
    return passed, sorted(found_types)


def _check_ingredient_limit(meals: List[Dict[str, Any]], limit: int):
    """No meal may have more than `limit` ingredients."""
    meals_over_limit = []
    for meal in meals:
        if len(meal["ingredients"]) > limit:
            meals_over_limit.append(meal.get("meal_name", "?"))
    passed = len(meals_over_limit) == 0
    return passed, meals_over_limit


def _is_forbidden(text: str, forbidden_terms: List[str], exceptions: List[str]) -> bool:
    """True if `text` contains a forbidden term and no exception phrase."""
    for exception in exceptions:
        if exception in _norm(text):
            return False  # e.g. "gluten-free soy sauce" is allowed
    for term in forbidden_terms:
        if _contains_term(text, term):
            return True
    return False


def _check_forbidden(meals: List[Dict[str, Any]], forbidden_terms: List[str],
                     exception_phrases: List[str]):
    """No ingredient or meal name may contain a forbidden term (unless an exception applies)."""
    exceptions = [_norm(phrase) for phrase in exception_phrases]

    hits = set()
    for meal in meals:
        # Meal names are scanned too: "Chicken Curry" is a violation even if "chicken" isn't listed.
        texts_to_check = meal["ingredients"] + [str(meal.get("meal_name", ""))]
        for text in texts_to_check:
            if text and _is_forbidden(text, forbidden_terms, exceptions):
                hits.add(text)

    passed = len(hits) == 0
    return passed, sorted(hits)


def _check_pantry_excluded(shopping_list: Optional[List[str]], pantry: List[str]):
    """No shopping-list entry may be something already in the pantry."""
    pantry_items = [item for item in pantry if _norm(item)]  # ignore blank pantry entries

    leaked = []
    for item in shopping_list or []:
        for pantry_item in pantry_items:
            if _is_pantry_item(item, pantry_item):
                leaked.append(item)
                break
    passed = len(leaked) == 0
    return passed, leaked


def score_run(case: Dict[str, Any], meal_plan: Optional[List[Dict[str, Any]]],
              shopping_list: Optional[List[str]]) -> Dict[str, Any]:
    """Return {check_name: bool} plus details for every expectation in the case.

    Only the checks listed in the case's `expect` block are run. Every check fails when
    there is no meal plan. Malformed meals (missing keys, wrong types) fail the relevant
    checks instead of raising.
    """
    expect = case.get("expect", {})
    checks: Dict[str, bool] = {}
    details: Dict[str, Any] = {}

    meals = _meals(meal_plan)
    has_plan = len(meals) > 0

    # valid_plan: there is a plan, and every entry in it is a well-formed meal.
    malformed_count = len(meal_plan) - len(meals) if has_plan else 0
    checks["valid_plan"] = has_plan and malformed_count == 0
    if malformed_count > 0:
        details["malformed_meals"] = malformed_count

    if "days" in expect:
        passed, detail = _check_day_count(meals, expect["days"])
        checks["days"] = has_plan and passed
        details["days"] = detail

    if "meal_types" in expect:
        passed, detail = _check_meal_types(meals, expect["meal_types"])
        checks["meal_types"] = has_plan and passed
        details["meal_types"] = detail

    if "max_ingredients_per_meal" in expect:
        passed, detail = _check_ingredient_limit(meals, expect["max_ingredients_per_meal"])
        checks["max_ingredients_per_meal"] = has_plan and passed
        details["meals_over_ingredient_limit"] = detail

    if "forbidden_ingredients" in expect:
        passed, detail = _check_forbidden(meals, expect["forbidden_ingredients"],
                                          expect.get("forbidden_exceptions", []))
        checks["forbidden_ingredients"] = has_plan and passed
        details["forbidden_hits"] = detail

    if expect.get("shopping_list_excludes_pantry"):
        passed, detail = _check_pantry_excluded(shopping_list, case.get("pantry", []))
        checks["shopping_list_excludes_pantry"] = has_plan and passed
        details["pantry_items_in_shopping_list"] = detail

    all_passed = all(checks.values())
    return {"passed": all_passed, "checks": checks, "details": details}


# ============ LLM JUDGE ============

JUDGE_SYSTEM = """You are a strict evaluator of meal plans produced by a grocery assistant.
You are given the user's messages and the meal plan. Judge ONLY the plan against what the user asked.

Answer with a single JSON object and nothing else:
{
  "diet_compliant": true|false,   // every meal respects all stated restrictions and allergies,
                                  // including implied ingredients (e.g. pasta, bread, soy sauce
                                  // contain gluten; pesto usually contains nuts; gelatin is not vegetarian)
  "matches_request": true|false,  // days, meals per day, and preferences (e.g. "quick") are honoured
  "coherent": true|false,         // each meal is a real, sensible dish and its ingredients fit its name
  "score": 1-5,                   // overall quality: 1 = unusable, 5 = excellent
  "issues": ["short description of each problem found"]
}"""

JUDGE_FIELDS = ("diet_compliant", "matches_request", "coherent")


def build_judge_messages(case: Dict[str, Any], meal_plan: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    user_turns = "\n".join(f"- {t}" for t in case["turns"])
    extra = case.get("expect", {}).get("judge_criteria")
    content = (f"User messages:\n{user_turns}\n\n"
               f"Meal plan:\n{json.dumps(meal_plan, indent=2, ensure_ascii=False)}")
    if extra:
        content += f"\n\nAdditional criteria:\n{extra}"
    return [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": content}]


def parse_judge_reply(reply: str) -> Dict[str, Any]:
    """Extract the judge's JSON verdict; return {'error': ...} if it can't be parsed."""
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        return {"error": "no JSON in judge reply", "raw": reply}
    try:
        verdict = json.loads(match.group())
    except json.JSONDecodeError as e:
        return {"error": f"invalid judge JSON: {e}", "raw": reply}
    if not isinstance(verdict, dict) or any(not isinstance(verdict.get(f), bool) for f in JUDGE_FIELDS):
        return {"error": "judge verdict missing boolean fields", "raw": reply}
    score = verdict.get("score")
    verdict["score"] = score if isinstance(score, (int, float)) and 1 <= score <= 5 else None
    verdict["issues"] = [str(i) for i in verdict.get("issues", [])] if isinstance(verdict.get("issues"), list) else []
    verdict["passed"] = all(verdict[f] for f in JUDGE_FIELDS)
    return verdict


def judge_run(case: Dict[str, Any], meal_plan: Optional[List[Dict[str, Any]]],
              generate_fn: Callable[[List[Dict[str, str]]], str]) -> Dict[str, Any]:
    """Ask an LLM to grade the plan. generate_fn takes chat messages and returns the reply text."""
    if not meal_plan:
        return {"passed": False, "score": None, "issues": ["no meal plan"],
                **{f: False for f in JUDGE_FIELDS}}
    try:
        return parse_judge_reply(generate_fn(build_judge_messages(case, meal_plan)))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ============ RUNNING ============

def _worker(model_path: str, case: Dict[str, Any], q: mp.Queue,
            judge_model: Optional[str] = None) -> None:
    transcript: List[str] = []
    turns_used = 0
    try:
        t0 = time.time()
        agent = Agent(model_path)
        load_time = time.time() - t0

        # Keep eval conversations out of the user's real memory file.
        tmpdir = tempfile.mkdtemp(prefix="grocery_eval_")
        agent.memory = Memory(storage_file=str(Path(tmpdir) / "conversation.json"))

        turns = iter(case["turns"])

        def scripted_input(prompt: str = "") -> str:
            nonlocal turns_used
            try:
                text = next(turns)
            except StopIteration:
                text = "exit"
            else:
                turns_used += 1
            transcript.append(f"{prompt}{text}")
            return text

        t1 = time.time()
        meal_plan = agent.generate_meal_plan(input_fn=scripted_input, output_fn=transcript.append)
        meal_time = time.time() - t1

        t2 = time.time()
        shopping_list = agent.generate_shopping_list(meal_plan, pantry_list=case["pantry"]) if meal_plan else []
        shopping_time = time.time() - t2

        judge, judge_time = None, None
        if judge_model:
            t3 = time.time()
            # Judge at temperature 0 so repeated grading of the same plan is stable.
            judge_agent = agent if judge_model == model_path else Agent(judge_model)
            judge = judge_run(case, meal_plan,
                              lambda msgs: judge_agent.generate_text(msgs, temperature=0.0, max_tokens=512))
            judge_time = time.time() - t3

        q.put({
            "meal_plan": meal_plan,
            "shopping_list": shopping_list,
            "turns_used": turns_used,
            "load_time": load_time,
            "meal_time": meal_time,
            "shopping_time": shopping_time,
            "judge": judge,
            "judge_time": judge_time,
            "transcript": transcript,
            "error": None,
        })
    except Exception as e:
        q.put({"meal_plan": None, "shopping_list": None, "turns_used": turns_used,
               "transcript": transcript, "error": f"{type(e).__name__}: {e}"})


def run_once(model_path: str, case: Dict[str, Any], timeout: int,
             judge_model: Optional[str] = None) -> Dict[str, Any]:
    q: mp.Queue = mp.Queue()
    p = mp.Process(target=_worker, args=(model_path, case, q, judge_model))
    p.start()
    try:
        # Read before join: a child blocked writing a large result to the queue never exits.
        return q.get(timeout=timeout)
    except Exception:
        return {"meal_plan": None, "shopping_list": None, "error": "timeout"}
    finally:
        if p.is_alive():
            p.terminate()
        p.join()


def _rate(values: List[bool]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _judge_summary(runs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    verdicts = [r["judge"] for r in runs if isinstance(r.get("judge"), dict)]
    if not verdicts:
        return None
    graded = [v for v in verdicts if "error" not in v]
    scores = [v["score"] for v in graded if v.get("score") is not None]
    return {
        "pass_rate": _rate([v["passed"] for v in graded]),
        **{f"{f}_rate": _rate([v[f] for v in graded]) for f in JUDGE_FIELDS},
        "avg_score": round(mean(scores), 2) if scores else None,
        "judge_errors": len(verdicts) - len(graded),
    }


def evaluate(model_path: str, cases: List[Dict[str, Any]], repeats: int = 3, timeout: int = 300,
             output: str = "eval_results.json", judge_model: Optional[str] = None) -> Dict[str, Any]:
    runs = []
    case_summaries = {}

    for case in cases:
        case_runs = []
        for i in range(max(1, repeats)):
            print(f"[{case['id']}] run {i + 1}/{repeats} ...", flush=True)
            result = run_once(model_path, case, timeout, judge_model)
            score = score_run(case, result.get("meal_plan"), result.get("shopping_list"))
            run = {"case": case["id"], "repeat": i + 1, **result, **score}
            print(f"  passed={score['passed']} checks={score['checks']} error={result.get('error')}")
            if result.get("judge"):
                j = result["judge"]
                print(f"  judge: passed={j.get('passed')} score={j.get('score')} "
                      f"issues={j.get('issues')} error={j.get('error')}")
            case_runs.append(run)
        runs.extend(case_runs)

        check_names = case_runs[0]["checks"].keys()
        meal_times = [r["meal_time"] for r in case_runs if r.get("meal_time") is not None]
        case_summaries[case["id"]] = {
            "pass_rate": _rate([r["passed"] for r in case_runs]),
            "check_pass_rates": {c: _rate([r["checks"][c] for r in case_runs]) for c in check_names},
            "errors": sum(1 for r in case_runs if r.get("error") and r["error"] != "timeout"),
            "timeouts": sum(1 for r in case_runs if r.get("error") == "timeout"),
            "avg_turns_used": round(mean(r.get("turns_used", 0) for r in case_runs), 2),
            "avg_meal_time_s": round(mean(meal_times), 2) if meal_times else None,
        }
        judge_summary = _judge_summary(case_runs)
        if judge_summary:
            case_summaries[case["id"]]["judge"] = judge_summary

    summary = {
        "model": Path(model_path).name,
        "temperature": config.LLM_TEMPERATURE,
        "cases": len(cases),
        "repeats": repeats,
        "overall_pass_rate": _rate([r["passed"] for r in runs]),
        "errors": sum(s["errors"] for s in case_summaries.values()),
        "timeouts": sum(s["timeouts"] for s in case_summaries.values()),
        "per_case": case_summaries,
    }
    if judge_model:
        summary["judge_model"] = Path(judge_model).name
        summary["judge"] = _judge_summary(runs)

    results = {"summary": summary, "runs": runs}
    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nSaved evaluation to {output}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return results


def _cli():
    p = argparse.ArgumentParser(description="Evaluate the Agent against a golden dataset.")
    p.add_argument("--model", "-m", default=config.MODEL_PATH, help="Path to MLX model directory")
    p.add_argument("--cases", "-c", default=DEFAULT_CASES, help="JSONL file of golden cases")
    p.add_argument("--case", action="append", help="Only run the case with this id (repeatable)")
    p.add_argument("--repeats", "-n", type=int, default=3, help="Runs per case")
    p.add_argument("--timeout", "-t", type=int, default=300, help="Timeout (seconds) per run, including model load")
    p.add_argument("--output", "-o", default="eval_results.json", help="Output JSON file for results")
    p.add_argument("--judge-model", "-j", default=None,
                   help="MLX model directory used as an LLM judge (omit to run rule checks only). "
                        "Pass the same path as --model to reuse the loaded model.")
    args = p.parse_args()

    cases = load_cases(args.cases)
    if args.case:
        unknown = set(args.case) - {c["id"] for c in cases}
        if unknown:
            p.error(f"unknown case id(s): {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in args.case]
    evaluate(args.model, cases, args.repeats, args.timeout, args.output, args.judge_model)


if __name__ == "__main__":
    _cli()
