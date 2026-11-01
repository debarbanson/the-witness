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
- `hard_cases.json`: 24 harder cases on the same kept quotes: near
  numbers (unit swaps, off-by-one amounts, date arithmetic), near
  dates (off-by-one days, built/lit conflation), right year with the
  wrong event, stated negations accepted and flipped, scope
  overstatements, and plans stated as events. Every quote grounded
  against kept `research.json` by `tests/test_eval.py`.
- `run_support_eval.py`: runs both arms (6 workers each) under a $3
  spending cap and writes `<set>_results_<date>.json`.
- `support_results_*.json`, `hard_results_*.json`: raw per-case
  verdicts, latency and cost.

Run: `.venv/bin/python eval/run_support_eval.py --set support|hard`
(keys from `.env.local`, like the CLI). Smoke: `EVAL_SMOKE=1` runs
the first accept plus the first reject of the chosen set.
