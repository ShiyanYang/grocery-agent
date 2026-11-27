# Production-Grade Code Review & Improvements

_Last updated: 2026-11-27_

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
19. ✅ **Unit tests** (`test/`, pytest, 80 tests, all passing): the LLM is mocked, so no model is needed.
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
37. ✅ **Friendlier GUI redesign**: a warm kitchen theme with chat bubbles, tap-to-answer suggestions, the meal plan as day cards, a tick-off shopping list, and the agent's internal status messages hidden or turned into plain words.

### Round 6: judge and agent prompts
38. ✅ **Judge prompt follows the [Hugging Face LLM-as-a-judge guide](https://huggingface.co/learn/cookbook/llm_judge)**:
    every score from 1 to 5 now has a description (before, only 1 and 5 did), and the judge writes `issues` before
    its verdict and score, so it looks for problems before it decides. In the next full run the judge still gave a 5
    ("no issues") to 2 plans while listing an issue.
39. ✅ **Pantry prompt asks for every ingredient**: `_pantry_instruction()` in `agent.py` tells the model that buying
    is expected and each meal must list every ingredient the dish needs, so plans no longer leave out ingredients
    that aren't in the pantry ("Lentil Soup" with only salt). On 5 cases × 3 runs: rule checks 14/15, judge 15/15,
    average judge score 4.73 (up from 3.33). The vegetarian case went from judge 0/3 to 3/3.

### Round 7: failure categories and a bigger eval
40. ✅ **Failure taxonomy** (`FAILURE_TAXONOMY.md`): six categories built from reading transcripts (`constraint`,
    `implied_ingredient`, `plan_shape`, `coherence`, `shopping_list`, `conversation`), plus a separate list of grader
    errors. Every eval case lists the categories it targets and a note on what correct behaviour looks like.
41. ✅ **14 new eval cases (19 in total)**: late allergy, change of mind, vague and conflicting requests, hidden
    ingredients, halal, a full week, and pantry edge cases.
42. ✅ **New `min_turns_used` rule check**: fails a plan made before a late turn (e.g. "Oh, I'm allergic to peanuts") was read.
43. ✅ **Pass rate per category** in the eval summary (`per_category`), and `python eval.py --category <name>` runs one category.
44. ✅ **Full eval run, 19 cases × 3 runs**: rule checks 44/57 (77%), judge 47/55 (85%). All 13 rule failures were real,
    and no plan broke a diet. The judge missed 4 real problems that the rules caught. New problems found are under
    High priority below.

### Round 8: following the requested meals
45. ✅ **Meal-type rule in the system prompt** (PR #1): a new rule "Plan only the meals the user asks for ... and
    do not add extra meals", and the schema example now uses `"<a meal the user asked for>"` instead of breakfast
    and lunch, which the model was copying. Tested without the judge (`eval_quick.json`, `eval_tier2_regression.json`):
    - The 3 cases that always failed: meal types right in **8/9 runs (was 0/9)**; all rule checks 7/9.
    - 3 cases that passed before: meal types right in every plan; 8/9 runs passed all rule checks.
    - The placeholder was never copied into a plan.
46. ✅ **Automatic PR review** (PR #2): `.github/workflows/pr-review.yml` runs Claude on every pull request and
    posts inline comments. Needs the `ANTHROPIC_API_KEY` repository secret.
47. ✅ **Meal-type safety net in code**: `generate_meal_plan` collects the meal types named in the user's own
    messages (`find_meal_types`: breakfast, lunch, dinner, snack), and `_check_meal_plan` rejects a plan with any
    other meal type, so self-repair sends "Remove lunch; only breakfast and dinner were requested." Repair feedback
    is not scanned, or its "Remove lunch" would make lunch look requested. Only extra meals are flagged, not
    missing ones, and "no lunch" still counts lunch as named, so negations can miss an extra meal but never reject
    a good plan. If no meal type was named, nothing is checked. Unit tests in `test/test_agent.py`.

---

## 🔴 High priority

### 1. The agent adds meals the user didn't ask for (mostly fixed)
The biggest problem in the 19-case run: in 9 runs, the user asked for certain meals in the same message as diet
rules, and the plan added breakfast or lunch anyway. The prompt rule (item 45) cut this from 9/9 to 1/9 runs on
the same cases: `conflict_vegan_cheese_omelette` still added lunch once. The code check (item 47) now rejects such
a plan and asks for a fix. In the next run of the same 6 cases × 3 runs, meal types were right in all 18 runs, but
the model got them right on its own, so the check never had to act.

Still to do:
- ~~**Safety net in code**~~: done (item 47). Unit tests cover the repair; the model hasn't yet added an extra
  meal in an eval run, so the repair hasn't yet been seen fixing a real plan.
- **Watch for side effects of the longer prompt**: in the item 45 runs, one `vegetarian_gluten_free_dairy_free`
  plan used a "whole wheat wrap" (gluten), the first diet break since the categories were added. All 3 runs in
  the item 47 run were clean, so it looks like chance (1 break in 6 runs); a run with `-n 5` would settle it.
- **Confirm with a full run with the judge**: the tests so far used rule checks only, on 6 of 19 cases.

### 2. A full week is too long for one reply
`full_week_three_meals` failed every run: at `LLM_MAX_TOKENS` = 1024, 2 runs timed out in the repair loop and 1
returned only 8 of 21 meals. Options: raise `LLM_MAX_TOKENS` for long plans, or generate the plan one day at a time
and join the days.

### 3. Ingredients bundled into one string
In 2 of 15 earlier runs, the model wrote each meal's ingredients as one comma-separated string
(`["pasta, canned tomatoes, olive oil, ..."]`). The schema accepts it, so neither grader noticed: the shopping
list became 4 long entries and pantry items weren't removed. Options: reject it in `_check_meal_plan` with repair
feedback, or split it in `_flatten_ingredients` (careful: `"boneless, skinless chicken breast"` is one item),
and add a rule check so the eval catches it. #9 (structured ingredients) would also prevent it.

### 4. Pantry matching still guesses from free text
The agent removes leaks like `chicken breasts` (item 30), but:
- Entries with unknown words such as `brown rice` vs pantry `rice` are kept on the list and need a human decision.
- **Quantities aren't handled**: `1 lb boneless chicken breast` and `1/4 cup extra virgin olive oil` are pantry items
  but were listed for review instead of removed. Strip leading amounts and units before matching.
- `diced` should be added to `SAME_ITEM_QUALIFIERS` in `ingredient_match.py`.
- **Duplicates**: `onion` and `onions` can both appear on the shopping list, and no rule check catches it.

Long term: see #9 (structured ingredients).

### 5. Doesn't plan when asked, and vague requests
In `vague_request`, 1 run kept asking questions even after "Please give me the meal plan now", so there was no plan,
and another built a 5-day plan from nothing. After item 45 it happened in a normal case too: in 1 of 3
`two_day_all_meals` runs (3/3 before), the model asked three more questions instead of planning. A prompt rule
such as "When the user asks for the plan, reply with the plan right away" targets it directly. The correct behaviour for this case (and for
`conflict_vegan_cheese_omelette`) is still marked **PRODUCT DECISION NEEDED** in its `note`: decide it, then make
the agent stop asking and plan with sensible defaults once the user asks for the plan.

### 6. Remaining grader errors
- **Judge passes plans while naming the problem**: the most common judge error. In the 19-case run it passed all
  3 vegan runs with an extra lunch while naming the lunch in `issues`, and gave a 5 to the 5-day vague plan although
  its criteria said a long invented plan isn't acceptable. Earlier, it passed gelatin cups (vegetarian) and granola
  ("no nuts") the same way. Options: tell the judge that any real issue means `pass: false`, or fail the run in
  code when `issues` is not empty and the score is below 5.
- **Rule false alarms**: "Crab-Free Tuna Wrap" fails the forbidden-ingredient check, and "brown rice tortilla" was
  flagged in a gluten-free plan. Ignore negated terms ("crab-free", "no crab") in meal names, and use
  `forbidden_exceptions` for items like "rice tortilla".
- **Judge is slow**: ~55 s per plan, adding ~50 minutes to a 57-run eval.
- **Human check of the judge**: the 37 labeled plans were judged by one person, only 1 real plan was bad,
  and the labels weren't saved, so the check can't be repeated. Following the Hugging Face guide:
  - Save the labels to a file (e.g. `eval_data/human_labels.jsonl`). Each label gets the same 1–5 score and
    yes/no fields as the judge.
  - Cover every score level, including bad plans (the guide uses about 7 per level). Have a second person label them if possible.
  - Add a script that reports agreement: correlation for the 1–5 score and percent agreement for each yes/no field.
  - Rerun it after every judge prompt or model change, so changes like item 38 are measured rather than assumed.

### 7. File locking for pantry/memory
Two processes writing `data/pantry.json` at once (e.g. `app.py` and the GUI, which now edits the pantry) can lose updates:
```python
from filelock import FileLock

def load_pantry():
    with FileLock("data/pantry.json.lock"):
        ...
```

### 8. The plan can have the wrong number of days
In the safety-net eval run (item 47), one `veg_3day_breakfast_dinner` run asked for 3 days and got a 1-day plan.
The eval's `days` rule caught it, but the agent accepted the plan. Add a day-count check like the meal-type
check:
- Track the requested number of days from the user's own messages. Keep the latest number, because users change
  their mind (`change_of_mind_number_of_days`: "make that 5 days instead of 3"). Accept digits and words ("3 days",
  "three days", "a week" → 7). If no number is found, don't check.
- In `_check_meal_plan`, count distinct day labels the same way as `_check_days` in `eval.py`. If the count is wrong,
  send specific feedback, e.g. "The plan has 1 day; 3 days were requested. Plan Day 1 to Day 3."
- Unit tests: parsing (digits, words, a change of mind, no number), the feedback text, and a repair run through
  `generate_meal_plan`.
- Watch `full_week_three_meals` (item 2): a 7-day plan already hits `LLM_MAX_TOKENS`, so a repair request for
  all 7 days may run out of tokens again.


---

## 🟠 Medium priority

### 9. Structured ingredients
Ingredients are free text, so every pantry comparison has to guess which words are the item ("cooked brown
rice", "1 lb boneless chicken breast"). Change each ingredient in `MEAL_PLAN_SCHEMA` to
`{"item": "chicken breast", "prep": "boneless", "amount": "1 lb"}` so the agent and the eval compare only `item`.
Needs a schema, prompt and `_flatten_ingredients` change, and an eval run to confirm the 8B model follows it.

### 10. Try Gemma 4 E4B as the agent model
It's far stronger than Llama 3 8B (MMLU-Pro ~69% vs ~41%) and smaller (5 GB vs 8 GB). It may also fix #1 (following
the requested meal types). Before switching: strip its thinking text in `generate_text` (the GUI shows replies as
they come), run the eval and compare transcripts. If it becomes the agent, change the judge too (e.g. test Gemma 4
26B-A4B), so the model isn't grading itself.

### 11. More tests and eval cases
- `pantry.py` and `memory.py` have no tests yet (load/save, missing or corrupt files).
- The eval now has 19 cases (item 41). Gaps from `FAILURE_TAXONOMY.md`:
  - A **change of mind after the plan** can't be tested, because the agent ends the conversation once it has a valid plan.
  - Add a rule check for **shopping-list duplicates** (#4).
  - Only 3 runs per case, so one run changes a case's pass rate by 33%. Use more runs for the cases that matter most.

### 12. Module docstrings and examples
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

### 13. Structured logging
JSON log format for production:
```python
class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"timestamp": self.formatTime(record), "level": record.levelname,
                           "logger": record.name, "message": record.getMessage()})
```

### 14. API layer
FastAPI/Flask endpoint. This needs the meal-plan conversation to work over requests instead of `input()`;
the injectable `input_fn`/`output_fn` are a first step, and the GUI (item 35) already drives the conversation this way:
```python
agent = Agent("./models/llama-3-8b-instruct-mlx")

@app.route("/meal-plan", methods=["POST"])
def generate_meal_plan():
    ...
```

### 15. Database instead of JSON files
SQLite for the pantry and memory (also solves #7):
```python
conn.execute("""CREATE TABLE IF NOT EXISTS pantry (
    id INTEGER PRIMARY KEY, item TEXT UNIQUE, added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
```

### 16. Packaging / deployment
MLX only runs on Apple Silicon macOS, so a standard Linux Docker image won't work. Options: a
`pyproject.toml` for installation, or support a second backend (e.g. llama-cpp or an API) for Linux/Docker.

---

## 🟡 Nice to have

17. **Custom exceptions**: `MealPlanGenerationError`, `PantryAccessError`
18. **CLI with Click/Typer**: e.g. `grocery plan --days 3`
19. **Monitoring**: generation time and repair attempts per request (eval already records timings)
20. **Graceful degradation**: fallback meal plan if the model fails to load
21. **Security**: sanitize ingredient names; rate limiting if exposed via an API
22. **Async generation** (only matters once there's an API serving several users)

---

## Testing checklist

- [x] Unit tests for agent core functions
- [ ] Unit tests for `pantry.py` and `memory.py`
- [x] LLM output validation tests (schema, JSON, self-repair)
- [x] End-to-end eval of the meal-plan pipeline (`eval.py`)
- [x] Eval cases tagged by failure category, with per-category pass rates
- [x] Error handling tests for edge cases (None/empty plans, malformed meals)
- [ ] Memory persistence tests
- [ ] Concurrent access tests for pantry file operations
- [ ] Performance timings (recorded per run, but missing from the 19-case run because the Mac slept)
- [x] Grader validation against human verdicts (judge comparison on 37 labeled plans)
- [ ] Load testing with multiple users

---

## Next steps

1. **Now**
   - [x] Make the agent follow the requested meal types: prompt rule (item 45)
   - [ ] Meal-type check in `_check_meal_plan` as a safety net (#1)
   - [ ] Reply with the plan right away when the user asks for it (#5)
   - [ ] Fix full-week plans running out of tokens (#2)
   - [ ] Catch ingredients bundled into one string (agent + eval)
   - [ ] Rerun the eval with the Mac kept awake (`caffeinate -i python eval.py`) so timings are recorded
   - [x] Fresh `python eval.py` run with the new judge prompt, then update the README results table
   - [x] Pantry prompt asks for every ingredient (item 39)
   - [x] Failure categories and 14 new eval cases (items 40–44)
2. **Short term**
   - [ ] Judge: fail plans whose `issues` name a real problem
   - [ ] Fix the "Crab-Free" and "brown rice tortilla" false alarms
   - [ ] Pantry matching: strip quantities, add `diced`, catch duplicates (#4)
   - [ ] Decide the correct behaviour for the two PRODUCT DECISION NEEDED cases (#5)
   - [ ] Save human labels to a file, with an agreement script
   - [ ] Tests for `pantry.py` / `memory.py`
   - [ ] File locking
   - [ ] Run the GUI end to end with the MLX model
   - [ ] Pin all installed versions (`pip freeze > requirements.lock`)
   - [x] Stronger judge model; spot-check verdicts
   - [x] Shape-specific repair feedback for nested meal plans
   - [x] Config/repo cleanup and finish the repo rename
   - [x] GUI runs the real agent, with pantry editing and a meal-plan table
3. **Medium term**
   - [ ] Structured ingredients (`item` + `prep` + `amount`)
   - [ ] Try Gemma 4 E4B as the agent model
   - [x] Bigger eval dataset (5 → 19 cases)
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
