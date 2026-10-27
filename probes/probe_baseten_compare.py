"""Compare Meta vs Baseten support checks on the fixed regression claims.

Passages come from live Wikipedia extracts through the production
fetch plus select path, so both providers judge identical jobs.
Completion stays on Meta. Prints agreement, verdicts, time and tokens.
"""
import sys
import time

sys.path.insert(0, ".")

from witness import cli, models, verify

JOBS = [
    # (claim, event, detail, year, article url)
    ("decorated: tower decorated with tulips since 1986.", "decorated",
     "Decorated with tulips.", 1986,
     "https://nl.wikipedia.org/wiki/Watertoren_(Roelofarendsveen)"),
    ("built: De Adriaan built in 1779.", "built",
     "Built in 1779.", 1779,
     "https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem"),
    ("burnt: De Adriaan completely burnt down in 1932.", "burnt",
     "Completely burnt down.", 1932,
     "https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem"),
    ("restored: De Adriaan restored in 1963.", "restored",
     "Took an obligation to rebuild; the promise fell into oblivion.",
     1963, "https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem"),
    ("rebuilt: De Adriaan reopened in 2002.", "rebuilt",
     "Reopened in 2002.", 2002,
     "https://en.wikipedia.org/wiki/De_Adriaan,_Haarlem"),
    ("moved-proposed: 1967 plan to dismantle the Eiffel Tower.", "moved-proposed",
     "Secret agreement to dismantle and relocate.", 1967,
     "https://en.wikipedia.org/wiki/Eiffel_Tower"),
]


def build_jobs():
    jobs = []
    for claim, event, detail, year, url in JOBS:
        text = verify.fetch_source_text(url)
        keywords = verify.keywords_for_claim(claim, event)
        paras = verify.select_paragraphs(text, year, keywords, max_paras=3)
        jobs.append({"claim": claim, "event": event, "detail": detail,
                     "year": year, "keywords": keywords,
                     "passages": [f"{url}\n{p}" for p in paras],
                     "urls": [url], "votes": 3})
    return jobs


def main():
    jobs = build_jobs()
    models.reset_usage()
    start = time.perf_counter()
    meta = verify.judge_all(cli.support_respond, jobs,
                            completion_respond=cli.support_respond)
    meta_s = time.perf_counter() - start
    start = time.perf_counter()
    alt = verify.judge_all(cli.baseten_support_respond, jobs, completion=False)
    alt_s = time.perf_counter() - start
    compared = cli.compare_verdicts(jobs, meta, alt)
    for job, mine, other in zip(jobs, meta, alt):
        print(f"{job['year']} {job['event']}: meta={mine['verdict']} "
              f"open={other['verdict']} completed={mine['completed']}")
    print(f"agreement: {compared['agree']}/{compared['total']}")
    print(f"time: meta {meta_s:.1f}s, open {alt_s:.1f}s")
    print(f"tokens: {models.usage_totals()}")


if __name__ == "__main__":
    main()
