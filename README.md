# 🛒 Grocery Agent

A local AI agent that chats with you to build a multi-day meal plan, then turns it into a shopping list
that skips what's already in your pantry. It runs Llama 3 8B on-device with [MLX](https://github.com/ml-explore/mlx).

> 📚 Personal project in building, testing and evaluating an LLM agent.

## Setup

Requires an **Apple Silicon Mac** (MLX) and ~10 GB free disk space.

```bash
git clone https://github.com/ShiyanYang/grocery-agent.git grocery_agent
cd grocery_agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Put an MLX model in `models/llama-3-8b-instruct-mlx/`, for example by converting from Hugging Face:

```bash
mlx_lm.convert --hf-path meta-llama/Meta-Llama-3-8B-Instruct \
  --mlx-path models/llama-3-8b-instruct-mlx -q --q-bits 8
```

Settings (model path, temperature, file locations) live in `config.py` and can be overridden with
environment variables or a `.env` file (see `.env.example`).

## Usage

```bash
python main.py      # chat to create a meal plan, then print the shopping list
python run_gui.py   # same meal planner in a desktop window, with pantry editing and a meal-plan table
python app.py       # manage the pantry: list, add <item>, remove <item>, help, quit
```

## Project structure

```
agent.py          # LLM agent: meal-plan conversation, JSON validation and self-repair, shopping list
pantry.py         # pantry storage (data/pantry.json)
memory.py         # conversation history (memory/conversation.json)
config.py         # settings with env-var overrides
main.py, app.py   # CLI entry points (meal planner, pantry manager)
chat_gui.py       # Tkinter GUI for the meal planner (run via run_gui.py)
eval.py           # evaluation harness
eval_data/        # golden eval cases (JSONL), each tagged with failure categories
FAILURE_TAXONOMY.md  # failure categories the eval cases target, and grader errors
test/             # unit tests (pytest)
```

## Testing & evaluation

```bash
pip install -r requirements-dev.txt   # once, adds pytest
pytest test/                      # unit tests (no model needed), with a live progress bar
pytest test/ -v                   # same, listing each test by name
python eval.py                    # run the agent on eval_data/meal_plan_cases.jsonl, graded by rules + LLM judge
python eval.py --no-judge         # rule checks only (faster)
python eval.py --category conversation   # only the cases tagged with one failure category
```

The judge is Gemma 4 E4B (`models/gemma-4-e4b-it-4bit`, set by `JUDGE_MODEL_PATH`). Download it with
`hf download mlx-community/gemma-4-e4b-it-4bit --local-dir models/gemma-4-e4b-it-4bit`. On 37 hand-labeled
plans it agreed with the human verdict 35 times (Llama 3 8B: 29), but it takes ~55 s per plan.

Each eval case runs several times and is scored with rule checks: day count, meal types,
forbidden ingredients, and pantry items leaking into the shopping list. Shopping items that might be pantry
items (e.g. `brown rice` vs pantry `rice`) don't fail the run; they're listed under `possible_pantry_items`
for review. Words that never change an item are in `SAME_ITEM_QUALIFIERS` in `ingredient_match.py`. The LLM judge additionally
grades diet compliance (including implied ingredients), whether the plan matches the request, and whether
the meals make sense. Results are saved to `eval_results.json`.

The judge prompt (`JUDGE_SYSTEM` in `eval.py`) follows the
[Hugging Face LLM-as-a-judge guide](https://huggingface.co/learn/cookbook/llm_judge):
- It uses a small 1–5 score with a description for every level, not a wide or unexplained scale.
- The judge lists `issues` before giving its verdict and score, so it looks for problems before it decides.
- Its answer is JSON, which `parse_judge_reply` checks, and it runs at temperature 0 so repeated grading is stable.

### Latest results

Agent: Llama 3 8B (MLX), temperature 0.7. Judge: Gemma 4 E4B. 19 cases × 3 runs (`eval_results.json`).

**By failure category.** A case can have several categories (see [FAILURE_TAXONOMY.md](FAILURE_TAXONOMY.md)).

| Category | Cases | Rule checks passed | Judge passed |
|---|:-:|:-:|:-:|
| `shopping_list` | 7 | 100% | 100% |
| `coherence` | 4 | 92% | 92% |
| `plan_shape` | 4 | 75% | 90% |
| `conversation` | 5 | 73% | 93% |
| `constraint` | 11 | 73% | 82% |
| `implied_ingredient` | 5 | 60% | 60% |
| **Overall** | **19** | **77% (44/57)** | **85% (47/55)**¹ |

A category's pass rate counts a run as failed if *any* check fails, not just the check for that category.
`constraint` and `implied_ingredient` look low, but no plan broke a diet: those cases failed `meal_types`.


Reading all 57 plans by hand:
- **All 13 rule-check failures are real.** There were no false alarms this run.
- **No plan broke a diet.** Late allergies, changes of mind, meat in a vegetarian's pantry and hidden gluten
  (the model used gluten-free soy sauce and rice noodles) were all handled correctly.
- **Biggest problem: the agent ignores which meals were asked for** when the same message also lists diet rules.
  9 runs added breakfast or lunch the user didn't ask for. Mostly fixed since; see below.
- **A full week is too long a reply.** At `LLM_MAX_TOKENS` = 1024, 2 runs timed out in the repair loop and 1 returned
  only 8 of 21 meals.
- **Vague request:** 1 run kept asking questions even after "Please give me the meal plan now", so there was no plan.
  Another built a 5-day plan from nothing.
- **The judge missed 4 real problems; the rules missed none.** The judge passed all 3 vegan runs with an extra lunch
  while naming it in `issues`, and gave a 5 to the 5-day vague plan even though its criteria said a long invented
  plan isn't acceptable.
- **Pantry matching doesn't handle quantities.** `1 lb boneless chicken breast` and `1/4 cup extra virgin olive oil`
  are pantry items but were listed for review instead of removed. `diced` should be a same-item qualifier.
- **Times aren't reported** because the Mac slept during the run. A plan normally takes ~50–70 s, plus ~30 s for the judge.

### After the meal-type prompt fix

The system prompt now says to plan only the meals the user asks for, and its example no longer shows breakfast and
lunch. Tested on 6 cases × 3 runs, rule checks only (no judge):

| Cases | Meal types right | All rule checks passed | Other failures |
|---|:-:|:-:|---|
| The 3 that always added meals (`eval_quick.json`) | 8/9 (was 0/9) | 7/9 | 1 extra lunch; 1 "whole wheat wrap" in a gluten-free plan |
| 3 that passed before (`eval_tier2_regression.json`) | 8/8 plans | 8/9 | 1 run asked more questions instead of planning |

A full 19-case run with the judge is still to do.

## Known limitations

- Pantry matching works on free-text ingredient names (`ingredient_match.py`). Entries like `brown rice` vs pantry
  `rice` stay on the shopping list, because they may be a different item.
- Meal plans are extracted from the model's reply with a regex, then schema-validated and sent back for repair if invalid.
- Single-user: pantry and memory are plain JSON files with no concurrent-access handling.

See [PRODUCTION_IMPROVEMENTS.md](PRODUCTION_IMPROVEMENTS.md) for planned work.

## License

MIT, see [LICENSE](LICENSE).
