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
17. ✅ **Self-repair loop**: invalid JSON or schema violations are sent back to the model with specific feedback, up to `MAX_REPAIR_ATTEMPTS` times
18. ✅ **Injectable I/O**: `generate_meal_plan(input_fn, output_fn)` so conversations can be scripted (used by tests and eval)
19. ✅ **Unit tests** (`test/`, pytest, 59 tests): shopping list, pantry filtering, meal-plan parsing, self-repair, eval scoring and judge parsing. The LLM is mocked, so no model is needed.
20. ✅ **Evaluation harness** (`eval.py`):
    - Golden dataset of scripted conversations (`eval_data/meal_plan_cases.jsonl`)
    - Each case runs N times in its own process, with a timeout
    - Rule checks: day count, meal types, forbidden ingredients (incl. meal names), pantry leaks
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
28. ✅ **Three-way pantry check** in the eval:
    - **Leak** (fails): the pantry item plus only words from `SAME_ITEM_QUALIFIERS` (fresh, chopped, boneless, skinless, large, organic, extra virgin, cooked, table)
    - **Possible** (passes, listed under `possible_pantry_items` and in the summary for review): unknown leading words, e.g. "brown rice" ~ "rice"
    - **Different item** (ignored): e.g. "rice vinegar" ~ "rice"
    - Re-scoring the last run removed 3 false alarms (8/15 → 11/15); real leaks like "chicken breasts" still fail
29. ✅ **README results** re-graded with the new judge and pantry check: rule checks 11/15, judge 14/15

---

## 🔴 High priority

### 1. Pantry matching in the agent is exact
The eval now catches leaks like `chicken breasts` vs pantry `chicken breast` (2 of the last 15 runs), but the
agent's `_filter_out_pantry_items()` still only removes exact matches, so these items end up on the shopping list.
Short term: reuse the eval's leak rules in the agent. Long term: see #8 (structured ingredients).

### 2. `jsonschema` missing from `requirements.txt`
`agent.py` imports it, so a fresh install fails with `ModuleNotFoundError`.

### 3. Failing self-repair test
`test_invalid_json_plan_is_sent_back_and_fixed` reads
`call_args_list[1].args[0][-1]`, but the mock holds a reference to the `messages` list, which `_ask` appends
the reply to afterwards. Read `[-2]` (or copy the messages in the mock) instead.

### 4. Remaining grader errors
- **Meal-name false alarm**: "Crab-Free Tuna Wrap" fails the forbidden-ingredient check. Ignore negated
  terms ("crab-free", "no crab") in meal names.
- **Judge passes plans while naming the problem**: Gemma marked gelatin cups (vegetarian) and granola
  ("no nuts") compliant but listed them in `issues`. Read `issues` on passing runs too.
- **Judge is slow**: ~55 s per plan, adding ~14 minutes to a 15-run eval.
- The 37 labeled plans were judged by one person (and only 1 real plan was bad). Save the labels to a
  file (e.g. `eval_data/human_labels.jsonl`) with a script that reports grader agreement, and add more bad examples.

### 5. Plans in the wrong JSON shape
1 of the last 15 runs produced no plan: the model nested meals inside each day (`{"day": ..., "meals": [...]}`),
and the generic "not valid JSON" repair feedback didn't fix it in 2 attempts. Give feedback that names the
expected shape.

### 6. File locking for pantry/memory
Two processes writing `data/pantry.json` at once (e.g. `app.py` and the GUI) can lose updates:
```python
from filelock import FileLock

def load_pantry():
    with FileLock("data/pantry.json.lock"):
        ...
```

---

## 🟠 Medium priority

### 7. Clean up config and repo leftovers
- `LLM_N_CTX` and `LLM_N_THREADS` are llama-cpp leftovers that MLX doesn't use; remove them.
- `models/llama-3-8b-instruct.gguf` (4.7 GB) is no longer used.
- Repo rename to `grocery-agent`: the README clone URL is updated, but the git remote, the CONTRIBUTING clone
  URL, the `receipt_agent` variable in `main.py` and `receipt_agent.textClipping` still use the old name.

### 8. Structured ingredients
Ingredients are free text, so every pantry comparison has to guess which words are the item ("cooked brown
rice"). Change each ingredient in `MEAL_PLAN_SCHEMA` to `{"item": "chicken breast", "prep": "boneless"}` so the
agent and the eval compare only `item`. Needs a schema, prompt and `_flatten_ingredients` change, and an eval
run to confirm the 8B model follows it.

### 9. Try Gemma 4 E4B as the agent model
It's far stronger than Llama 3 8B (MMLU-Pro ~69% vs ~41%) and smaller (5 GB vs 8 GB). Before switching:
strip its thinking text in `generate_text`, raise the GUI's 200-token limit, run the eval and compare
transcripts. If it becomes the agent, change the judge too (e.g. test Gemma 4 26B-A4B), so the model isn't grading itself.

### 10. More tests
- `pantry.py` and `memory.py` have no tests yet (load/save, missing or corrupt files).
- Grow the eval dataset beyond 5 cases: allergies, conflicting requests, users who change their mind mid-conversation.

### 11. Module docstrings and examples
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

### 12. Structured logging
JSON log format for production:
```python
class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"timestamp": self.formatTime(record), "level": record.levelname,
                           "logger": record.name, "message": record.getMessage()})
```

### 13. API layer
FastAPI/Flask endpoint. This needs the meal-plan conversation to work over requests instead of `input()`;
the injectable `input_fn`/`output_fn` are a first step:
```python
agent = Agent("./models/llama-3-8b-instruct-mlx")

@app.route("/meal-plan", methods=["POST"])
def generate_meal_plan():
    ...
```

### 14. Database instead of JSON files
SQLite for the pantry and memory (also solves #6):
```python
conn.execute("""CREATE TABLE IF NOT EXISTS pantry (
    id INTEGER PRIMARY KEY, item TEXT UNIQUE, added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
```

### 15. Packaging / deployment
MLX only runs on Apple Silicon macOS, so a standard Linux Docker image won't work. Options: a
`pyproject.toml` for installation, or support a second backend (e.g. llama-cpp or an API) for Linux/Docker.

---

## 🟡 Nice to have

16. **Custom exceptions**: `MealPlanGenerationError`, `PantryAccessError`
17. **CLI with Click/Typer**: e.g. `grocery plan --days 3`
18. **Monitoring**: generation time and repair attempts per request (eval already records timings)
19. **Graceful degradation**: fallback meal plan if the model fails to load
20. **Security**: sanitize ingredient names; rate limiting if exposed via an API
21. **Async generation** (only matters once there's an API serving several users)

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
   - [ ] Add `jsonschema` to `requirements.txt`
   - [ ] Fix the failing self-repair test
   - [ ] Leak-aware pantry matching in the agent
   - [ ] Fresh `python eval.py` run, so `eval_results.json` matches the README table and includes judge scores
2. **Short term**
   - [x] Stronger judge model; spot-check verdicts
   - [ ] Fix the "Crab-Free" meal-name false alarm
   - [ ] Shape-specific repair feedback for nested meal plans
   - [ ] Save human labels to a file, with an agreement script
   - [ ] Tests for `pantry.py` / `memory.py`
   - [ ] File locking
   - [ ] Config/repo cleanup and finish the repo rename
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
