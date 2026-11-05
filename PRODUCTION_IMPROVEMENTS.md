# Production-Grade Code Review & Improvements

_Last updated: 2026-11-05_

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
17. ✅ **Self-repair loop**: invalid JSON, schema violations or meals over `MAX_INGREDIENTS_PER_MEAL` are sent back to the model with specific feedback, up to `MAX_REPAIR_ATTEMPTS` times
18. ✅ **Injectable I/O**: `generate_meal_plan(input_fn, output_fn)` so conversations can be scripted (used by tests and eval)
19. ✅ **Unit tests** (`test/`, pytest, 40 tests): shopping list, pantry filtering, meal-plan parsing, self-repair, eval scoring and judge parsing. The LLM is mocked, so no model is needed.
20. ✅ **Evaluation harness** (`eval.py`):
    - Golden dataset of scripted conversations (`eval_data/meal_plan_cases.jsonl`)
    - Each case runs N times in its own process, with a timeout
    - Rule checks: day count, meal types, ingredient limit, forbidden ingredients (incl. meal names), pantry leaks (plural/qualifier aware)
    - Optional **LLM judge** (`--judge-model`): diet compliance, matches request, coherence, 1–5 score
    - Per-case and overall pass rates and timings saved to `eval_results.json`; latest results in README
21. ✅ **Desktop chat GUI** (`chat_gui.py`, run via `run_gui.py`)
22. ✅ **Test & Quality agent** definition for coding assistants (`.github/agents/test-quality.agent.md`)
23. ✅ **README simplified** and updated for MLX

---

## 🔴 High priority

### 1. Pantry matching is exact
The eval's only failing rule check is pantry leaks (11/15 runs pass): `_filter_out_pantry_items()` only
removes exact matches, so `chicken breasts` and `table salt` end up on the shopping list even though
`chicken breast` and `salt` are in the pantry. Use plural- and qualifier-aware matching like
`_is_pantry_item()` in `eval.py`, and keep the two in sync.
Also fix the eval false positive: `sweet potatoes` is currently treated as pantry `potatoes`.

### 2. `jsonschema` missing from `requirements.txt`
`agent.py` imports it, so a fresh install fails with `ModuleNotFoundError`.

### 3. Two failing self-repair tests
`test_over_limit_plan_is_sent_back_and_fixed` and `test_invalid_json_plan_is_sent_back_and_fixed` read
`call_args_list[1].args[0][-1]`, but the mock holds a reference to the `messages` list, which `_ask` appends
the reply to afterwards. Read `[-2]` (or copy the messages in the mock) instead.

### 4. LLM judge is unreliable
Llama 3 8B judging its own plans makes factual mistakes (calls eggs non-vegetarian, tuna shellfish).
Use a stronger judge model, then check 10–20 verdicts by hand before trusting judge pass rates.

### 5. File locking for pantry/memory
Two processes writing `data/pantry.json` at once (e.g. `app.py` and the GUI) can lose updates:
```python
from filelock import FileLock

def load_pantry():
    with FileLock("data/pantry.json.lock"):
        ...
```

---

## 🟠 Medium priority

### 6. Clean up config and repo leftovers
- `LLM_N_CTX` and `LLM_N_THREADS` are llama-cpp leftovers that MLX doesn't use; remove them.
- `models/llama-3-8b-instruct.gguf` (4.7 GB) is no longer used.
- Rename the GitHub repo from `receipt_agent` (suggested: `grocery-agent`), and update clone URLs in
  README/CONTRIBUTING, the `receipt_agent` variable in `main.py`, and delete `receipt_agent.textClipping`.

### 7. More tests
- `pantry.py` and `memory.py` have no tests yet (load/save, missing or corrupt files).
- Grow the eval dataset beyond 5 cases: allergies, conflicting requests, users who change their mind mid-conversation.

### 8. Module docstrings and examples
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

### 9. Structured logging
JSON log format for production:
```python
class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"timestamp": self.formatTime(record), "level": record.levelname,
                           "logger": record.name, "message": record.getMessage()})
```

### 10. API layer
FastAPI/Flask endpoint. This needs the meal-plan conversation to work over requests instead of `input()`;
the injectable `input_fn`/`output_fn` are a first step:
```python
agent = Agent("./models/llama-3-8b-instruct-mlx")

@app.route("/meal-plan", methods=["POST"])
def generate_meal_plan():
    ...
```

### 11. Database instead of JSON files
SQLite for the pantry and memory (also solves #5):
```python
conn.execute("""CREATE TABLE IF NOT EXISTS pantry (
    id INTEGER PRIMARY KEY, item TEXT UNIQUE, added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
```

### 12. Packaging / deployment
MLX only runs on Apple Silicon macOS, so a standard Linux Docker image won't work. Options: a
`pyproject.toml` for installation, or support a second backend (e.g. llama-cpp or an API) for Linux/Docker.

---

## 🟡 Nice to have

13. **Custom exceptions**: `MealPlanGenerationError`, `PantryAccessError`
14. **CLI with Click/Typer**: e.g. `grocery plan --days 3`
15. **Monitoring**: generation time and repair attempts per request (eval already records timings)
16. **Graceful degradation**: fallback meal plan if the model fails to load
17. **Security**: sanitize ingredient names; rate limiting if exposed via an API
18. **Async generation** (only matters once there's an API serving several users)

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
- [ ] Load testing with multiple users

---

## Next steps

1. **Now**
   - [ ] Add `jsonschema` to `requirements.txt`
   - [ ] Fix the two failing self-repair tests
   - [ ] Fuzzy pantry matching in the agent
2. **Short term**
   - [ ] Stronger judge model; spot-check verdicts
   - [ ] Tests for `pantry.py` / `memory.py`
   - [ ] File locking
   - [ ] Config/repo cleanup and repo rename
3. **Medium term**
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
- Estimate prices for the shopping list

**Code quality**
- Refactor the code for readability (started with `score_run` in `eval.py`)
- Understand the tests
