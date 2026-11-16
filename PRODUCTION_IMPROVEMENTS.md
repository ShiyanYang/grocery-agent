# Production-Grade Code Review & Improvements

_Last updated: 2026-11-16_

## ✅ Completed

### Round 1: bug fixes and code quality
1. ✅ **Fixed `search_pantry()` missing return**: it now returns the pantry list.
2. ✅ **Fixed `Memory.get_all()` missing return**: it now returns a copy of the items.
3. ✅ **Fixed function name typo**: `generate_shoppling_list` → `generate_shopping_list`.
4. ✅ **Fixed type errors**: `_normalize()` validates its input type.
5. ✅ **Logging** in all modules.
6. ✅ **Type hints and docstrings** on functions.
7. ✅ **Input validation and error handling** with clear error messages.
8. ✅ **Memory persistence**: conversations are saved to disk.
9. ✅ **Atomic file operations**: the pantry is saved via a temporary file.
10. ✅ **Better CLI UX**: `app.py` has help, case-insensitive commands and better feedback.
11. ✅ **Graceful exits** in `main.py`: exit codes and Ctrl-C handling.

### Round 2: infrastructure, reliability and evaluation
12. ✅ **`.gitignore`**: models and generated files are excluded.
13. ✅ **Configuration module** (`config.py`): defaults, env-var and `.env` overrides, dev/prod/testing profiles, model validation.
14. ✅ **Switched from llama-cpp (GGUF) to MLX**: the model loads from a local MLX directory.
15. ✅ **Model cache**: `Agent.get_model()` loads each model once and reuses it.
16. ✅ **JSON schema validation** of meal plans (`MEAL_PLAN_SCHEMA` + `jsonschema`).
17. ✅ **Self-repair loop**: invalid plans are sent back to the model with specific feedback, up to `MAX_REPAIR_ATTEMPTS` times.
18. ✅ **Injectable I/O**: `generate_meal_plan(input_fn, output_fn)` lets tests, the eval and the GUI script the conversation.
19. ✅ **Unit tests** (`test/`, pytest, 74 tests, all passing): the LLM is mocked, so no model is needed.
20. ✅ **Evaluation harness** (`eval.py`): scripted cases run several times each and are graded by rule checks and an LLM judge; results go to `eval_results.json` and the README.
21. ✅ **Desktop chat GUI** (`chat_gui.py`, run via `run_gui.py`).
22. ✅ **Test & Quality agent** definition for coding assistants (`.github/agents/test-quality.agent.md`).
23. ✅ **README simplified** and updated for MLX.

### Round 3: making the eval trustworthy
24. ✅ **Readable `score_run`**: one small function per check, verified identical to the old version on 20,000 random inputs.
25. ✅ **Removed the 7-ingredient limit**: it was arbitrary, and repairs for it made the model pad meals with "water" and "butter".
26. ✅ **Human review of grader verdicts** (30 runs): most of the Llama judge's fails were wrong, and the rule check's errors were pantry false alarms like `brown rice` vs `rice`.
27. ✅ **New judge model, Gemma 4 E4B with thinking on**: right on 35/37 hand-labeled plans (Llama 3 8B: 29/37), but takes ~54 s per plan.
28. ✅ **Three-way pantry check** in the eval: an entry is a leak (fail), a possible pantry item (listed for review) or a different item; this removed 3 false alarms.
29. ✅ **Fresh eval run** with all fixes: rule checks 14/15, judge 14/15, judge score 4.40.

### Round 4: fixing the agent and setup
30. ✅ **Leak-aware pantry filter in the agent**: it uses the eval's rules, now shared in `ingredient_match.py`, so leaks like `chicken breasts` are removed. Since both share the rules, review `possible_pantry_items` to catch mistakes in them.
31. ✅ **Complete, pinned dependencies**: added `jsonschema`, pinned `mlx-lm==0.31.3`, and added `requirements-dev.txt` with `pytest`. Packages that `mlx-lm` depends on aren't pinned yet.
32. ✅ **Self-repair diagnoses nested plans correctly**: the full JSON value is parsed, so nested plans get schema feedback with an example instead of a wrong "not valid JSON". Not yet exercised in a full eval run.
33. ✅ **Fixed the failing self-repair test**: the fake model now saves a copy of the messages it receives on each call.
34. ✅ **Cleaned up config and repo leftovers**: removed unused llama-cpp settings, fixed `.env.example`, and finished renaming `receipt_agent` to `grocery-agent`.

### Round 5: chat GUI
35. ✅ **GUI runs the real agent**: `chat_gui.py` runs `generate_meal_plan()` and `generate_shopping_list()` on a worker thread, like `main.py`, with `agent.py` unchanged. Tested with a fake agent only.
36. ✅ **GUI usability**: editable pantry panel, the meal plan as a table with a per-meal "To buy" column, speaker icons, and a processing animation instead of the spinning wheel.

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
Two processes writing `data/pantry.json` at once (e.g. `app.py` and the GUI, which now edits the pantry) can lose updates:
```python
from filelock import FileLock

def load_pantry():
    with FileLock("data/pantry.json.lock"):
        ...
```

### 5. Delete the unused GGUF model
The 4.7 GB `.gguf` file from the llama-cpp setup is no longer used since the switch to MLX.

---

## 🟠 Medium priority

### 6. Structured ingredients
Ingredients are free text, so every pantry comparison has to guess which words are the item ("cooked brown
rice"). Change each ingredient in `MEAL_PLAN_SCHEMA` to `{"item": "chicken breast", "prep": "boneless"}` so the
agent and the eval compare only `item`. Needs a schema, prompt and `_flatten_ingredients` change, and an eval
run to confirm the 8B model follows it.

### 7. Try Gemma 4 E4B as the agent model
It's far stronger than Llama 3 8B (MMLU-Pro ~69% vs ~41%) and smaller (5 GB vs 8 GB). Before switching:
strip its thinking text in `generate_text` (the GUI shows replies as they come), run the eval and compare
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
the injectable `input_fn`/`output_fn` are a first step, and the GUI (item 35) already drives the conversation this way:
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
   - [x] Config/repo cleanup and finish the repo rename
   - [x] GUI runs the real agent, with pantry editing and a meal-plan table
   - [ ] Run the GUI end to end with the MLX model
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
