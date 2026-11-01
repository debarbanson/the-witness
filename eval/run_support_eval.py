"""One support vote per case per model over a named case set.

Compares the open-weights path (Baseten Muse Spark Open) with Meta
(muse-spark-1.3) on identical votes: verify_claim, completion off, one
vote each. Writes eval/<set>_results_<date>.json with every verdict,
latency and cost. Keys load from .env.local like the CLI; nothing is
printed but the summary. Budget: refuses to start past $3 reserved.
"""

import contextlib
import io
import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from witness import cli as cli_module  # noqa: E402
from witness import models, verify  # noqa: E402

MAX_USD = 3.0
WORKERS = 6

CASE_SETS = {
    "support": "support_cases.json",
    "hard": "hard_cases.json",
}


def load_cases(name="support"):
    """Cases for a named set; unknown names raise KeyError."""
    return json.loads((HERE / CASE_SETS[name]).read_text())


def results_path(name="support"):
    """Results file for a named set, dated today."""
    return HERE / f"{name}_results_{date.today().isoformat()}.json"


def one_vote(respond, case):
    """A single production support vote; verdict plus seconds."""
    passage = f"{case['url']}\n{case['quote']}"
    started = time.perf_counter()
    try:
        answer = verify.verify_claim(respond, case["claim"], [passage])
        verdict = answer.get("verdict", "error")
    except Exception as exc:  # noqa: BLE001 - recorded, never thrown
        verdict = f"error: {exc.__class__.__name__}"
    return verdict, round(time.perf_counter() - started, 1)


def open_vote(case):
    """The production Baseten path, flagging any Meta fallback."""
    out = io.StringIO()
    with contextlib.redirect_stderr(out):
        verdict, seconds = one_vote(cli_module.baseten_support_respond, case)
    return verdict, seconds, "meta fallback" in out.getvalue()


def run_arm(cases, vote, label):
    print(f"{label}: {len(cases)} votes over {WORKERS} workers...",
          flush=True)
    results = {}
    with models.job_ledger() as ledger:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [models.submit_context(pool, vote, case)
                       for case in cases]
            for case, future in zip(cases, futures, strict=True):
                results[case["id"]] = future.result()
                if ledger.cost_usd > MAX_USD:
                    raise SystemExit(f"over ${MAX_USD}; stopping")
        cost = ledger.cost_usd
    print(f"{label}: ${cost:.3f} reserved cost", flush=True)
    return results, cost


def summarize(cases, results):
    right = {model: 0 for model in ("open", "meta")}
    accepts = {model: 0 for model in ("open", "meta")}
    true_total = sum(1 for c in cases if c["expected"] == "accept")
    seconds = {"open": [], "meta": []}
    for case in cases:
        for model in ("open", "meta"):
            verdict = results[case["id"]][model]["verdict"]
            accepted = verdict == "supported"
            if accepted:
                accepts[model] += 1
            if accepted == (case["expected"] == "accept"):
                right[model] += 1
            seconds[model].append(results[case["id"]][model]["seconds"])
    out = {}
    for model in ("open", "meta"):
        caught = sum(1 for c in cases
                     if c["expected"] == "accept"
                     and results[c["id"]][model]["verdict"] == "supported")
        out[model] = {
            "cases": len(cases),
            "right": right[model],
            "precision": round(caught / accepts[model], 3)
            if accepts[model] else 1.0,
            "recall": round(caught / true_total, 3) if true_total else 1.0,
            "mean_s": round(sum(seconds[model]) / len(seconds[model]), 1)
            if seconds[model] else 0.0,
        }
    return out


def main(argv=None) -> int:
    import argparse
    import os as _os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", default="support", choices=sorted(CASE_SETS),
                        help="case set to run")
    args = parser.parse_args(argv)
    cli_module.load_dotenv()
    tmp = Path(tempfile.mkdtemp(prefix="eval-spending-"))
    models.configure_spending(authority=models.BudgetAuthority(
        tmp, daily_cap_usd=MAX_USD))
    try:
        cases = load_cases(args.set)
        if _os.environ.get("EVAL_SMOKE"):
            accept = next(c for c in cases if c["expected"] == "accept")
            reject = next(c for c in cases if c["expected"] == "reject")
            cases = [accept, reject]
        by_id = {case["id"]: case for case in cases}
        opened, open_cost = run_arm(
            cases, open_vote, "open-weights (Baseten)")
        metad, meta_cost = run_arm(
            cases,
            lambda case: (*one_vote(cli_module.support_respond, case),
                          False),
            "meta (muse-spark-1.3)")
        results = {}
        for case in cases:
            verdict, seconds, fell_back = opened[case["id"]]
            meta_verdict, meta_seconds, _ = metad[case["id"]]
            results[case["id"]] = {
                "group": case["group"], "expected": case["expected"],
                "open": {"verdict": verdict, "seconds": seconds,
                         "fell_back": fell_back},
                "meta": {"verdict": meta_verdict,
                         "seconds": meta_seconds},
            }
        summary = summarize(cases, results)
        summary["open"]["cost_usd"] = round(open_cost, 4)
        summary["meta"]["cost_usd"] = round(meta_cost, 4)
        summary["open"]["fallbacks"] = sum(
            1 for case in cases if results[case["id"]]["open"]["fell_back"])
        payload = {"date": date.today().isoformat(), "cases": len(cases),
                   "results": results, "summary": summary,
                   "eval_cost_usd": round(open_cost + meta_cost, 4)}
        out = results_path(args.set)
        out.write_text(json.dumps(payload, indent=1))
        print(json.dumps(summary, indent=1))
        print(f"wrote {out}")
        print(f"case ids covered: {sorted(by_id) == sorted(results)}")
        return 0
    finally:
        models.configure_spending(None)


if __name__ == "__main__":
    raise SystemExit(main())
