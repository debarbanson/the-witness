# AGENTS.md

Instructions for any coding agent working in this repository.

## Read first

1. `docs/02_pipeline.md`: the steps, the exact API calls and the open TEST items.
2. `docs/03_accuracy.md`: the rules every film must follow.
3. `docs/05_build_log.md`: what exists today.

## Rules

- **Test first.** Write the failing pytest test, watch it fail, then implement. Pure logic (claim filtering, compositing, caption timing) is unit-tested; API calls sit behind small functions that tests replace with recorded responses.
- **Verify before building on an API fact.** If `docs/02_pipeline.md` marks something TEST, prove it with one real call and record the result in the build log before code depends on it.
- **No secrets in the repository.** Keys live in `.env.local` (ignored by git). Never print a key.
- **The object is never generated.** Always composite the SAM cut-out over painted eras.
- **No source, no claim.** Never let an unverified claim reach a caption.
- **Small steps.** One pipeline step per change, each runnable from the command line on a real photo.
- **Update the build log** at the end of each working day: what was built, what was proven, what changed.
- No em-dashes in docs or comments; British English.

## Layout

```
witness/          the package (one module per pipeline step)
  segment.py  research.py  verify.py  paint.py  layers.py  render/
tests/            pytest, with recorded API responses in tests/fixtures
out/              generated films (ignored by git)
```

## Commands

```bash
python -m pytest
python -m witness film <photo> --subject "<noun>" --place "<place>"
```
