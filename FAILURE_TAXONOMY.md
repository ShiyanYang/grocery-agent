# Failure taxonomy

The ways the meal-plan agent has failed, or could fail, grouped into categories. Every eval case in
`eval_data/meal_plan_cases.jsonl` lists the categories it targets in its `categories` field. The eval
summary reports a pass rate per category (`per_category`), and `python eval.py --category conversation` runs
only the cases in one category.

Built from reading eval transcripts by hand: note each problem in plain words, group the notes, then count.
Add a category when a new kind of failure shows up. Don't invent categories in advance.

| Category | What goes wrong | Seen in eval runs | Caught by |
|---|---|---|---|
| `constraint` | The plan breaks a diet, allergy or religious rule the user stated | chicken in a pescatarian plan | rule: `forbidden_ingredients`, judge: `diet_compliant` |
| `implied_ingredient` | A forbidden ingredient is hidden inside another one | granola in a "no nuts" plan; soy sauce contains gluten | judge (rules only catch words on the list) |
| `plan_shape` | Wrong days or meal types, or the JSON has the wrong shape | meals grouped inside days; ingredients in one string; cut-off JSON | rules: `days`, `meal_types`, `valid_plan`; schema + self-repair in the agent |
| `coherence` | Meals aren't real dishes, or ingredients don't match the name | "Lentil Soup" with only salt; veggie broth on avocado toast | judge: `coherent` only |
| `shopping_list` | Buys what's in the pantry, or lists the same item twice | pantry leaks (`chicken breasts`); `onion` and `onions` both listed | rule: `shopping_list_excludes_pantry` (duplicates: not checked yet) |
| `conversation` | Ignores a later turn, plans too early, or misreads a change of mind | none yet: newly tested | rule: `min_turns_used`, judge: `judge_criteria` |

## Grader errors (a separate category)

These are mistakes by the eval, not the agent. Track them so you know how much to trust the numbers.

| Error | Example | Fix |
|---|---|---|
| Rule false alarm | "Crab-Free Quinoa Salad"; "Brown rice tortilla" in a gluten-free plan | add `forbidden_exceptions`; handle "-free" words |
| Judge too lenient | gave 5 ("no issues") while listing an issue; passed granola in a "no nuts" plan | check the judge against human labels |
| Judge misuses fields | writes praise in `issues` | prompt wording; human labels |

## Known gaps

- A **change of mind after the plan** can't be tested: the agent ends the conversation once it has a valid plan.
- **Shopping-list duplicates** (`onion` / `onions`) have no rule check.
- Cases marked **PRODUCT DECISION NEEDED** in their `note` (`vague_request`, `conflict_vegan_cheese_omelette`)
  use a proposed correct behaviour that still needs to be confirmed.
