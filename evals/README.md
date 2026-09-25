# Evals

Each eval is a scenario: a prompt a scientist would type, the data it needs,
and a grader that checks the outcome (the notebook runs, the right structure is
shown, the numbers match the source).

Two uses:

1. **Does a skill help?** Run the scenario with and without it.
2. **Which model can do it?** Run the scenario against each model behind the
   LLM gateway before we promise it to anyone.

Public benchmarks (LAB-Bench, BixBench…) come later.
