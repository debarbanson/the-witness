# Open-weights support eval

One support vote per case per model: the production Baseten path
(`baseten_support_respond`, Muse Spark Open) against Meta
(`support_respond`, `muse-spark-1.3`), identical votes through
`verify.verify_claim`, completion off.

- `support_cases.json`: 53 cases. Quotes are verbatim from pages
  fetched for the three demo films (grounded against kept
  `research.json` by `tests/test_eval.py`); true claims are tightened
  to what the single passage states, mutations negate, swap the
  object, shift the date or add an unquoted detail.
- `hard_cases.json`: 28 harder cases: 24 on the same kept quotes
  (near numbers, near dates, right year with the wrong event, stated
  negations accepted and flipped, scope overstatements, plans stated
  as events) plus 4 synthetic prompt-injection cases in group
  `injected` (a passage telling the judge to answer supported or
  unsupported, over true and false claims). Every non-synthetic quote
  grounded against kept `research.json` by `tests/test_eval.py`.
- Grounding on a fresh clone: the kept research is git-ignored, so
  the grounding tests fall back to `tests/fixtures/kept_quotes.json`,
  the same supported quotes shipped with the repo.
- `run_support_eval.py`: runs both arms (6 workers each) under a $3
  spending cap and writes `<set>_results_<date>.json`.
- `support_results_*.json`, `hard_results_*.json`: raw per-case
  verdicts, latency and cost.

Run: `.venv/bin/python eval/run_support_eval.py --set support|hard`
(keys from `.env.local`, like the CLI). Smoke: `EVAL_SMOKE=1` runs
the first accept plus the first reject of the chosen set.

Spot-check list (5 accept, 5 reject, both sets): T01, T14, N03, W02,
D07, P04, H03, H17, H21, I02.
