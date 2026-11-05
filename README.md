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
python run_gui.py   # same, in a desktop chat window
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
pytest test/                      # unit tests (no model needed)
python eval.py                    # run the agent on eval_data/meal_plan_cases.jsonl
python eval.py --judge-model ./models/llama-3-8b-instruct-mlx   # also grade with an LLM judge
```

Each eval case runs several times and is scored with rule checks: day count, meal types, ingredient limit,
forbidden ingredients, and pantry items leaking into the shopping list. The optional LLM judge additionally
grades diet compliance (including implied ingredients), whether the plan matches the request, and whether
the meals make sense. Results are saved to `eval_results.json`.

### Latest results

Llama 3 8B (MLX) as both agent and judge, temperature 0.7, 5 cases × 3 runs.

| Case | Rule checks passed | Failed rule check | Judge passed | Judge score (1–5) | Avg meal-plan time |
|---|:-:|---|:-:|:-:|--:|
| `veg_3day_breakfast_dinner` | 2/3 | pantry leak: `table salt` | 0/3 | 2.33 | 76.7 s |
| `two_day_all_meals` | 3/3 | — | 3/3 | 5.00 | 51.4 s |
| `gluten_free_1day` | 2/3 | pantry leak: `Sweet potatoes`¹ | 2/3 | 4.00 | 33.3 s |
| `dinner_only_4day_stocked_pantry` | 1/3 | pantry leak: `boneless chicken breasts`, `chicken breasts`, `cooked rice` | 3/3 | 4.00 | 43.6 s |
| `pescatarian_2day_lunch` | 3/3 | — | 1/3 | 3.00 | 32.4 s |
| **Overall** | **11/15 (73%)** | | **9/15 (60%)** | **3.67** | |

All failed rule checks are pantry leaks: the agent's pantry filter only removes exact matches.
¹ False positive: sweet potatoes aren't potatoes.
The judge is unreliable when grading its own model's output (e.g. it called eggs non-vegetarian),
so treat judge numbers as rough until a stronger judge model is used.

## Known limitations

- Pantry matching is exact: `chicken breasts` isn't recognised as pantry `chicken breast`.
- Meal plans are extracted from the model's reply with a regex, then schema-validated and sent back for repair if invalid.
- Single-user: pantry and memory are plain JSON files with no concurrent-access handling.

See [PRODUCTION_IMPROVEMENTS.md](PRODUCTION_IMPROVEMENTS.md) for planned work.

## License

MIT, see [LICENSE](LICENSE).
