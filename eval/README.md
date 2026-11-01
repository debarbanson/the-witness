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
- `run_support_eval.py`: runs both arms (6 workers each) under a $3
  spending cap and writes `support_results_<date>.json`.
- `support_results_*.json`: raw per-case verdicts, latency and cost.

Run: `.venv/bin/python eval/run_support_eval.py` (keys from
`.env.local`, like the CLI). Smoke: `EVAL_SMOKE=1` runs 2 cases.
