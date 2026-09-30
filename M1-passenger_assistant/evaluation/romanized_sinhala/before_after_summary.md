# Romanized Sinhala support: before / after

56 hand-written romanized-Sinhala (Singlish) and English queries, evaluated
offline against `detect_language` / `classify_intent` / `extract_entities`
directly (no server, no LLM - see `run_eval.py`). "Before" is the `main`
branch before this feature; "after" is this branch.

| Metric | Before | After |
|---|---|---|
| Language detection | 10.7% | **100.0%** |
| Intent classification | 23.2% | **100.0%** |
| Origin station (from_station) | 62.5% | **100.0%** |
| Destination station (to_station) | 44.6% | **100.0%** |
| **All four fields correct** | **10.7%** | **100.0%** |

The 6 English-only queries in the set (ids 51-56) already scored correctly
"before" - they are included as a regression guard, not as part of the
improvement. Excluding them, the romanized-Sinhala-only subset (50 queries)
went from ~0% (nothing was recognized as Sinhala at all - every romanized
message was tagged `language=en`, and `intent=unknown` for the large
majority) to 100%.

## How to reproduce

```
# "after" (this branch)
<venv>/python.exe evaluation/romanized_sinhala/run_eval.py

# "before" (compare against main)
git stash                 # keep this evaluation/ folder untracked, stash tracked backend/ changes
<venv>/python.exe evaluation/romanized_sinhala/run_eval.py
git stash pop
```

## Why "before" wasn't simply 0%

A few romanized messages already partially worked by accident:
- `intent=booking_request` sometimes matched anyway when the sentence
  contained the *English* word "book" (e.g. row 2, 5, 10) - the pre-existing
  English keyword loop in `intent_classifier.py` still ran.
- A few `from_station`/`to_station` values came through because the
  station name text (e.g. "matarata", "jaffnata") happened to already begin
  with the bare English-alias substring ("kandy", "jaffna") that
  `STATION_ALIASES` already listed - just with no role (origin/destination)
  assigned, since the role logic only understands English "from"/"to" and
  Sinhala-*script* case markers.

Every one of those partial hits is exactly what `nlu/romanized.py` targets
directly and correctly, rather than by coincidence.

## Development note

This 100% is measured against a curated 56-query set built for this feature
by hand and iterated against - it demonstrates the mechanism works
end-to-end on the intents/stations/phrasings that mechanism was designed to
match, not free-form generalization. See `queries.csv` for the exact set.
Coverage beyond it (different verbs, further stations, romanized Tamil) is
listed as known scope, not measured here.
