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
for review. Words that never change an item are in `SAME_ITEM_QUALIFIERS` in `ingredient_match.py`. The LLM judge additionally
grades diet compliance (including implied ingredients), whether the plan matches the request, and whether
the meals make sense. Results are saved to `eval_results.json`.

The judge prompt (`JUDGE_SYSTEM` in `eval.py`) follows the
[Hugging Face LLM-as-a-judge guide](https://huggingface.co/learn/cookbook/llm_judge):
- It uses a small 1–5 score with a description for every level, not a wide or unexplained scale.
- The judge lists `issues` before giving its verdict and score, so it looks for problems before it decides.
- Its answer is JSON, which `parse_judge_reply` checks, and it runs at temperature 0 so repeated grading is stable.

### Latest results

Agent: Llama 3 8B (MLX), temperature 0.7. Judge: Gemma 4 E4B. 5 cases × 3 runs (`eval_results.json`).

| Case | Rule checks passed | Failed rule check | Judge passed | Judge score (1–5) | For review | Avg meal-plan time |
|---|:-:|---|:-:|:-:|---|--:|
| `veg_3day_breakfast_dinner` | 3/3 | — | 3/3 | 4.67 | judge: `veggie broth` in breakfasts | 52.8 s |
| `two_day_all_meals` | 3/3 | — | 3/3 | 4.67 | — | 61.4 s |
| `gluten_free_1day` | 2/3 | forbidden ingredient: `Brown rice tortilla`¹ | 3/3 | 5.00 | `sweet potatoes` | 43.1 s |
| `dinner_only_4day_stocked_pantry` | 3/3 | —² | 3/3 | 4.33 | — | 67.4 s |
| `pescatarian_2day_lunch` | 3/3 | — | 3/3 | 5.00 | — | 42.6 s |
| **Overall** | **14/15 (93%)** | | **15/15 (100%)** | **4.73** | | |

What changed since the last run: the agent prompt now says every meal must list all its ingredients, including ones
that must be bought, and the judge prompt describes every score level and asks for `issues` first. In the run
before, told to build meals around the pantry, the model listed only pantry items (e.g. "Lentil Soup" with just
`salt`); the rule checks passed 3/3 but the judge passed 0/3. Now every meal lists real ingredients.

Reading all 15 plans by hand, 13 are fine and 2 are borderline. None has a real problem:
- ¹ **False alarm:** `tortilla` is on the gluten-free list, but a brown rice tortilla is gluten-free. The plan is fine.
- ² **Borderline, passed by both graders:** one dinner run still leans on the pantry: "Grilled Chicken with Roasted
  Vegetables" lists only onion and garlic as vegetables, and the shopping list is just `tortillas`. The judge noted it
  but still gave a 5.
- **Borderline:** one vegetarian run puts `veggie broth` in avocado toast, scrambled tofu and an omelette.
- **Judge doesn't always follow its rubric:** it gave a 5 (meaning "no issues") to 2 plans while listing an issue,
  and sometimes writes praise in `issues`. A 15/15 judge pass rate can't be trusted until the judge is checked
  against human labels (see PRODUCTION_IMPROVEMENTS.md).
- **Shopping list duplicates:** `onion` and `onions` (and `veggie broth` and `vegetable broth`) can both appear,
  because duplicates are only removed when the text is exactly the same.
- **Not seen in this run:** ingredients bundled into one string. It isn't fixed, it just didn't happen.
- **For review:** shopping items that might be pantry items (they don't fail the run), plus judge issues.
- The judge took ~30 s per plan on top of the meal-plan time.

## Known limitations

- Pantry matching works on free-text ingredient names (`ingredient_match.py`). Entries like `brown rice` vs pantry
  `rice` stay on the shopping list, because they may be a different item.
- Meal plans are extracted from the model's reply with a regex, then schema-validated and sent back for repair if invalid.
- Single-user: pantry and memory are plain JSON files with no concurrent-access handling.

See [PRODUCTION_IMPROVEMENTS.md](PRODUCTION_IMPROVEMENTS.md) for planned work.

## License

MIT, see [LICENSE](LICENSE).
