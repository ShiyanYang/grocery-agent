# 🛒 Grocery Agent

A local AI agent that chats with you to build a multi-day meal plan, then turns it into a shopping list
that skips what's already in your pantry. It runs Llama 3 8B on-device with [MLX](https://github.com/ml-explore/mlx).

> 📚 Educational project: a learning exercise in building, testing and evaluating an LLM agent.

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
python run_gui.py   # desktop chat window for one-off questions (no meal-plan flow yet)
python app.py       # manage the pantry: list, add <item>, remove <item>, help, quit
```

## Project structure

```
agent.py          # LLM agent: meal-plan conversation, JSON validation and self-repair, shopping list
pantry.py         # pantry storage (data/pantry.json)
memory.py         # conversation history (memory/conversation.json)
config.py         # settings with env-var overrides
main.py, app.py   # CLI entry points (meal planner, pantry manager)
chat_gui.py       # Tkinter chat GUI (run via run_gui.py)
eval.py           # evaluation harness
eval_data/        # golden eval cases (JSONL)
test/             # unit tests (pytest)
```

## Testing & evaluation

```bash
pip install -r requirements-dev.txt   # once, adds pytest
pytest test/                      # unit tests (no model needed), with a live progress bar
pytest test/ -v                   # same, listing each test by name
python eval.py                    # run the agent on eval_data/meal_plan_cases.jsonl, graded by rules + LLM judge
python eval.py --no-judge         # rule checks only (faster)
```

The judge is Gemma 4 E4B (`models/gemma-4-e4b-it-4bit`, set by `JUDGE_MODEL_PATH`). Download it with
`hf download mlx-community/gemma-4-e4b-it-4bit --local-dir models/gemma-4-e4b-it-4bit`. On 37 hand-labeled
plans it agreed with the human verdict 35 times (Llama 3 8B: 29), but it takes ~55 s per plan.

Each eval case runs several times and is scored with rule checks: day count, meal types,
forbidden ingredients, and pantry items leaking into the shopping list. Shopping items that might be pantry
items (e.g. `brown rice` vs pantry `rice`) don't fail the run; they're listed under `possible_pantry_items`
for review. Words that never change an item are in `SAME_ITEM_QUALIFIERS` in `eval.py`. The LLM judge additionally
grades diet compliance (including implied ingredients), whether the plan matches the request, and whether
the meals make sense. Results are saved to `eval_results.json`.

### Latest results

Agent: Llama 3 8B (MLX), temperature 0.7. Judge: Gemma 4 E4B. 5 cases × 3 runs (`eval_results.json`).

| Case | Rule checks passed | Failed rule check | Judge passed | Judge score (1–5) | For review | Avg meal-plan time |
|---|:-:|---|:-:|:-:|---|--:|
| `veg_3day_breakfast_dinner` | 3/3 | — | 2/3 | 4.33 | judge: granola may contain nuts | 54.0 s |
| `two_day_all_meals` | 3/3 | — | 3/3 | 4.67 | — | 54.8 s |
| `gluten_free_1day` | 3/3 | — | 3/3 | 4.67 | `sweet potatoes`, `cooked brown rice` | 33.7 s |
| `dinner_only_4day_stocked_pantry` | 3/3¹ | — | 3/3 | 4.00 | — | 41.0 s |
| `pescatarian_2day_lunch` | 2/3 | forbidden ingredient: `Crab-Free Quinoa Salad`² | 3/3 | 4.33 | — | 34.6 s |
| **Overall** | **14/15 (93%)** | | **14/15 (93%)** | **4.40** | | |

Reading all 15 transcripts by hand, 12 runs are fine, 1 is borderline (granola in a "no nuts" plan) and 2 have a real problem:
- ¹ **Missed by both graders:** in 2 dinner runs the model wrote each meal's ingredients as *one* comma-separated
  string (`"pasta, canned tomatoes, olive oil, ..."`). The schema accepts it, the shopping list becomes 4 long
  entries, and pantry items like `pasta` and `olive oil` aren't removed.
- ² **False alarm:** the meal-name check matched "crab" in "Crab-Free". The plan is fine.
- **Fixed since the last run:** no pantry leaks (`chicken breasts` is now removed) and every run produced a valid
  plan. No plan needed a repair in this run, so the new nested-plan feedback wasn't exercised.
- **For review:** shopping items that might be pantry items (they don't fail the run), plus judge issues.
- The judge took ~29 s per plan on top of the meal-plan time.

## Known limitations

- Pantry matching works on free-text ingredient names (`ingredient_match.py`). Entries like `brown rice` vs pantry
  `rice` stay on the shopping list, because they may be a different item.
- Meal plans are extracted from the model's reply with a regex, then schema-validated and sent back for repair if invalid.
- Single-user: pantry and memory are plain JSON files with no concurrent-access handling.

See [PRODUCTION_IMPROVEMENTS.md](PRODUCTION_IMPROVEMENTS.md) for planned work.

## License

MIT, see [LICENSE](LICENSE).
