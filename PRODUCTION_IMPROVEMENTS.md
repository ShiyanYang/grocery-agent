# Production-Grade Code Review & Improvements

_Last updated: 2026-11-12_

## ✅ Completed

### Round 1: bug fixes and code quality
1. ✅ **Fixed `search_pantry()` missing return statement**: now returns the pantry list
2. ✅ **Fixed `Memory.get_all()` missing return statement**: now returns a copy of the items
3. ✅ **Fixed function name typo**: `generate_shoppling_list` → `generate_shopping_list`
4. ✅ **Fixed type errors**: type validation in `_normalize()`
5. ✅ **Logging** in all modules
6. ✅ **Type hints and docstrings** on functions
7. ✅ **Input validation and error handling** with clear error messages
8. ✅ **Memory persistence**: conversations saved to disk
9. ✅ **Atomic file operations**: pantry saves via a temporary file
10. ✅ **Better CLI UX**: `app.py` has help, case-insensitive commands and better feedback
11. ✅ **Graceful exits** in `main.py`: exit codes and Ctrl-C handling

### Round 2: infrastructure, reliability and evaluation
12. ✅ **`.gitignore`**: models and generated files are excluded
13. ✅ **Configuration module** (`config.py`): defaults, env-var overrides, `.env` support via `python-dotenv`, dev/prod/testing profiles, model validation
14. ✅ **Switched from llama-cpp (GGUF) to MLX**: the model is loaded from a local MLX directory
15. ✅ **Model cache**: `Agent.get_model()` loads each model once and reuses it across agent instances
16. ✅ **JSON schema validation** of meal plans (`MEAL_PLAN_SCHEMA` + `jsonschema`)
17. ✅ **Self-repair loop**: invalid JSON or schema violations are sent back to the model with specific feedback, up to `MAX_REPAIR_ATTEMPTS` times (feedback for nested plans fixed in item 32)
18. ✅ **Injectable I/O**: `generate_meal_plan(input_fn, output_fn)` so conversations can be scripted (used by tests and eval)
19. ✅ **Unit tests** (`test/`, pytest, 74 tests, all passing): shopping list, pantry filtering and leak rules, meal-plan extraction, self-repair, eval scoring and judge parsing. The LLM is mocked, so no model is needed. Install with `pip install -r requirements-dev.txt`.
20. ✅ **Evaluation harness** (`eval.py`):
    - Golden dataset of scripted conversations (`eval_data/meal_plan_cases.jsonl`)
    - Each case runs N times in its own process, with a timeout
    - Rule checks: day count, meal types, forbidden ingredients (incl. meal names), pantry leaks (three-way, see item 28)
    - **LLM judge** (on by default, `--no-judge` to skip): diet compliance, matches request, coherence, 1–5 score
    - Per-case and overall pass rates and timings saved to `eval_results.json`; latest results in README
21. ✅ **Desktop chat GUI** (`chat_gui.py`, run via `run_gui.py`)
22. ✅ **Test & Quality agent** definition for coding assistants (`.github/agents/test-quality.agent.md`)
23. ✅ **README simplified** and updated for MLX

### Round 3: making the eval trustworthy
24. ✅ **Readable `score_run`**: split into one small function per check with plain loops; verified identical to the old version on 20,000 random inputs and all saved runs
25. ✅ **Removed the 7-ingredient limit** (prompt rule, repair check, `MAX_INGREDIENTS_PER_MEAL`, eval check, dataset). It was an arbitrary number, and repairs for it made the model pad other meals with "water" and "butter".
26. ✅ **Human review of grader verdicts**: read all transcripts of two eval runs (30 runs) and marked each rule and judge verdict right or wrong. Findings:
    - The Llama judge's passes were reliable, but most of its fails were wrong ("tuna is shellfish", "quinoa contains gluten")
    - The rule check's errors were pantry false alarms ("brown rice" ~ "rice", "sweet potatoes" ~ "potatoes")
    - Decided: generic names are different items (`pepper` ≠ `black pepper`, `oil` ≠ `olive oil`), locked in by a test
27. ✅ **New judge model: Gemma 4 E4B** (`models/gemma-4-e4b-it-4bit`, `JUDGE_MODEL_PATH` in `config.py`)
    - Compared 3 setups on 37 hand-labeled plans (26 good, 11 bad, 10 of them deliberately broken):

      | Judge | Right | Good plans passed | Bad plans caught | Time/plan |
      |---|---|---|---|---|
      | Llama 3 8B | 29/37 | 19/26 | 10/11 | 9 s |
      | Gemma E4B, thinking off | 26/37 | 24/26 | 2/11 (9 unusable replies) | 12 s |
      | **Gemma E4B, thinking on** | **35/37** | **26/26** | **9/11** | **54 s** |
    - Different model family from the agent, so it isn't biased towards the agent's output
    - Its reasoning (thinking text) is stripped before the JSON verdict is parsed; `JUDGE_MAX_TOKENS` = 2048 so it isn't cut off
    - Gemma 4 12B was considered but needs `mlx-vlm`, which would have meant upgrading `mlx` and adding heavy dependencies
28. ✅ **Three-way pantry check** in the eval (`shopping_list_excludes_pantry`):
    - **Task:** the shopping list must not contain anything the user already has in their pantry.
    - **Fail:** a shopping-list entry is a pantry item, allowing plurals and words that don't change the item
      (`SAME_ITEM_QUALIFIERS`: fresh, chopped, boneless, skinless, large, organic, extra virgin, cooked, table).
      Example: pantry `chicken breast`, shopping list `boneless chicken breasts`.
    - **Success:** no shopping-list entry is a pantry item. A different item that shares a word doesn't count:
      pantry `rice`, shopping list `rice vinegar`; pantry `black pepper`, shopping list `pepper`.
    - **Needs review (still a success):** the pantry item ends the entry, but after a word that isn't in
      `SAME_ITEM_QUALIFIERS`, so it may be a different item. Example: pantry `rice`, shopping list `brown rice`.
      These entries are listed under `possible_pantry_items` and in the summary. If a word turns out never to
      change the item, add it to `SAME_ITEM_QUALIFIERS`.
    - **Result:** re-scoring the last run removed 3 false alarms (8/15 → 11/15); real leaks like `chicken breasts` still fail.
29. ✅ **README results** from a fresh eval run with all fixes: rule checks 14/15, judge 14/15, judge score 4.40 (12/15 runs fine on human review)
### Round 4: fixing the agent and setup
30. ✅ **Leak-aware pantry filter in the agent**: `_filter_out_pantry_items()` now uses the same rules as the eval,
    moved into a shared module, `ingredient_match.py` (`SAME_ITEM_QUALIFIERS`, `pantry_match`)
    - **Task:** the agent's shopping list must not contain anything already in the pantry.
    - **Fail (before):** only exact matches were removed, so `chicken breasts`, `boneless chicken breasts`,
      `table salt` and `cooked rice` stayed on the list.
    - **Success (now):** rebuilding the shopping lists of the 27 saved runs with a plan removes all 5 of those
      leaks, while `brown rice` and `sweet potatoes` stay on the list (they may be different items).
    - **Caveat:** the agent and the eval now share the same rules, so the eval's pantry check can no longer catch
      mistakes in those rules. Review `possible_pantry_items` and keep the tests in `test_agent.py` /
      `test_eval.py` up to date.
31. ✅ **Complete, pinned dependencies**
    - **Task:** a fresh `pip install` must give a working app and test setup, with the versions the project is tested on.
    - **Fail (before):** `jsonschema` was missing, so `agent.py` crashed with `ModuleNotFoundError`; `mlx-lm` was
      unpinned, so a fresh install got 0.32.2 instead of the tested 0.31.3; `pytest` wasn't listed at all.
    - **Success (now):** `requirements.txt` has `jsonschema==4.26.0` and `mlx-lm==0.31.3`, and the new
      `requirements-dev.txt` adds `pytest==9.1.1`. A dry-run install in a fresh virtual environment resolves cleanly.
    - **Still open:** packages that `mlx-lm` depends on aren't pinned (a fresh install gets `mlx` 0.32.4 and
      `transformers` 5.22.2 instead of 0.32.1 and 5.15.1). `pip freeze > requirements.lock` would pin everything.
32. ✅ **Self-repair diagnoses nested plans correctly** (`_check_meal_plan` in `agent.py`)
    - **Task:** when the model sends a broken plan, the repair feedback must say what is actually wrong.
    - **Fail (before):** the plan was found with the shortest `[{...}]` match. For a plan with meals nested inside
      each day (`{"day": ..., "meals": [...]}`), that cut the JSON off at the inner list, so the agent said
      "not valid JSON" about valid JSON. The model kept fixing commas, both repairs failed, and the run had no plan.
    - **Success (now):** the agent reads one complete JSON value from the first `[{`, so nested plans stay whole and
      fail the schema check instead. Schema feedback now includes the expected flat shape with an example
      (`PLAN_SHAPE_HELP`). Plans cut off mid-way now get "not valid JSON" feedback and a repair attempt; before,
      they were silently treated as a follow-up question.
    - **Checked:** on 188 real model replies, only the 6 nested-plan replies changed outcome, and no previously
      accepted plan changed (also 2,820 broken variants). Not yet confirmed in a full eval run: in the latest run
      no plan needed a repair, so whether the model fixes a nested plan after the new feedback is still untested.
    - Also simplified: a `MealPlan` type alias for `List[Dict[str, Any]]`, and plain `try` blocks.
33. ✅ **Fixed the failing self-repair test** (`test_invalid_json_plan_is_sent_back_and_fixed`)
    - **Task:** check that, after a broken plan, the model's second call receives the "not valid JSON" feedback.
    - **Fail (before):** the test read the mock's record of the messages, which is the same list the agent keeps adding
      to. By the time the test checked it, the last message was the model's reply, not the feedback.
    - **Success (now):** the fake model saves a copy of the messages it receives on each call, and the test checks
      that copy. The whole suite passes (74 tests).

---

## 🔴 High priority

### 1. Ingredients bundled into one string
In 2 of the last 15 runs, the model wrote each meal's ingredients as one comma-separated string
(`["pasta, canned tomatoes, olive oil, ..."]`). The schema accepts it, so neither grader noticed: the shopping
list became 4 long entries and pantry items weren't removed. Options: reject it in `_check_meal_plan` with repair
feedback, or split it in `_flatten_ingredients` (careful: `"boneless, skinless chicken breast"` is one item),
and add a rule check so the eval catches it. #6 (structured ingredients) would also prevent it.

### 2. Pantry matching still guesses from free text
The agent now removes leaks like `chicken breasts` (item 30), but entries with unknown words such as
`brown rice` vs pantry `rice` are kept on the list and need a human decision. Long term: see #6 (structured ingredients).

### 3. Remaining grader errors
- **Meal-name false alarm**: "Crab-Free Tuna Wrap" fails the forbidden-ingredient check. Ignore negated
  terms ("crab-free", "no crab") in meal names.
- **Judge passes plans while naming the problem**: Gemma marked gelatin cups (vegetarian) and granola
  ("no nuts") compliant but listed them in `issues`. Read `issues` on passing runs too.
- **Judge is slow**: ~55 s per plan, adding ~14 minutes to a 15-run eval.
- The 37 labeled plans were judged by one person (and only 1 real plan was bad). Save the labels to a
  file (e.g. `eval_data/human_labels.jsonl`) with a script that reports grader agreement, and add more bad examples.

### 4. File locking for pantry/memory
Two processes writing `data/pantry.json` at once (e.g. `app.py` and the GUI) can lose updates:
```python
from filelock import FileLock

def load_pantry():
    with FileLock("data/pantry.json.lock"):
        ...
```

---

## 🟠 Medium priority

### 5. Clean up config and repo leftovers
- `LLM_N_CTX` and `LLM_N_THREADS` are llama-cpp leftovers that MLX doesn't use; remove them.
- `models/llama-3-8b-instruct.gguf` (4.7 GB) is no longer used.
- Repo rename to `grocery-agent`: the README clone URL is updated, but the git remote, the CONTRIBUTING clone
  URL, the `receipt_agent` variable in `main.py` and `receipt_agent.textClipping` still use the old name.

### 6. Structured ingredients
Ingredients are free text, so every pantry comparison has to guess which words are the item ("cooked brown
rice"). Change each ingredient in `MEAL_PLAN_SCHEMA` to `{"item": "chicken breast", "prep": "boneless"}` so the
agent and the eval compare only `item`. Needs a schema, prompt and `_flatten_ingredients` change, and an eval
run to confirm the 8B model follows it.

### 7. Try Gemma 4 E4B as the agent model
It's far stronger than Llama 3 8B (MMLU-Pro ~69% vs ~41%) and smaller (5 GB vs 8 GB). Before switching:
strip its thinking text in `generate_text`, raise the GUI's 200-token limit, run the eval and compare
transcripts. If it becomes the agent, change the judge too (e.g. test Gemma 4 26B-A4B), so the model isn't grading itself.

### 8. More tests
- `pantry.py` and `memory.py` have no tests yet (load/save, missing or corrupt files).
- Grow the eval dataset beyond 5 cases: allergies, conflicting requests, users who change their mind mid-conversation.

### 9. Module docstrings and examples
`agent.py`, `pantry.py` and `memory.py` have no module docstring:
```python
"""
agent.py - AI agent for meal planning and shopping list generation.

Example:
    >>> from agent import Agent
    >>> agent = Agent("./models/llama-3-8b-instruct-mlx")
    >>> meal_plan = agent.generate_meal_plan()
    >>> shopping_list = agent.generate_shopping_list(meal_plan)
"""
```

### 10. Structured logging
JSON log format for production:
```python
class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"timestamp": self.formatTime(record), "level": record.levelname,
                           "logger": record.name, "message": record.getMessage()})
```

### 11. API layer
FastAPI/Flask endpoint. This needs the meal-plan conversation to work over requests instead of `input()`;
the injectable `input_fn`/`output_fn` are a first step:
```python
agent = Agent("./models/llama-3-8b-instruct-mlx")

@app.route("/meal-plan", methods=["POST"])
def generate_meal_plan():
    ...
```

### 12. Database instead of JSON files
SQLite for the pantry and memory (also solves #4):
```python
conn.execute("""CREATE TABLE IF NOT EXISTS pantry (
    id INTEGER PRIMARY KEY, item TEXT UNIQUE, added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
```

### 13. Packaging / deployment
MLX only runs on Apple Silicon macOS, so a standard Linux Docker image won't work. Options: a
`pyproject.toml` for installation, or support a second backend (e.g. llama-cpp or an API) for Linux/Docker.

---

## 🟡 Nice to have

14. **Custom exceptions**: `MealPlanGenerationError`, `PantryAccessError`
15. **CLI with Click/Typer**: e.g. `grocery plan --days 3`
16. **Monitoring**: generation time and repair attempts per request (eval already records timings)
17. **Graceful degradation**: fallback meal plan if the model fails to load
18. **Security**: sanitize ingredient names; rate limiting if exposed via an API
19. **Async generation** (only matters once there's an API serving several users)

---

## Testing checklist

- [x] Unit tests for agent core functions
- [ ] Unit tests for `pantry.py` and `memory.py`
- [x] LLM output validation tests (schema, JSON, self-repair)
- [x] End-to-end eval of the meal-plan pipeline (`eval.py`)
- [x] Error handling tests for edge cases (None/empty plans, malformed meals)
- [ ] Memory persistence tests
- [ ] Concurrent access tests for pantry file operations
- [x] Performance timings (per-run in eval results)
- [x] Grader validation against human verdicts (judge comparison on 37 labeled plans)
- [ ] Load testing with multiple users

---

## Next steps

1. **Now**
   - [x] Add `jsonschema` to `requirements.txt`
   - [x] Fix the failing self-repair test
   - [x] Leak-aware pantry matching in the agent
   - [x] Fresh `python eval.py` run, so `eval_results.json` matches the README table and includes judge scores
   - [ ] Catch ingredients bundled into one string (agent + eval)
2. **Short term**
   - [x] Stronger judge model; spot-check verdicts
   - [ ] Fix the "Crab-Free" meal-name false alarm
   - [x] Shape-specific repair feedback for nested meal plans
   - [ ] Save human labels to a file, with an agreement script
   - [ ] Tests for `pantry.py` / `memory.py`
   - [ ] File locking
   - [ ] Config/repo cleanup and finish the repo rename
   - [ ] Pin all installed versions (`pip freeze > requirements.lock`)
3. **Medium term**
   - [ ] Structured ingredients (`item` + `prep`)
   - [ ] Try Gemma 4 E4B as the agent model
   - [ ] Bigger eval dataset
   - [ ] Structured logging
   - [ ] API layer, database
4. **Long term**
   - [ ] Packaging / second backend for deployment
   - [ ] Monitoring, custom exceptions, CLI

---

## Ideas / notes

**New features**
- Generate images of meals
- Generate cooking steps
- Estimate prices for the shopping list using a tool

**Code quality**
- Refactor the code for readability (done for `score_run` in `eval.py`; others to go)
- Understand the tests
