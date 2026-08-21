# Extraction coverage

Produced by `make coverage` (`judgment/coverage.py`) against the labelled
artifact set in `corpus/data/artifacts.jsonl`. Regenerated in CI; a drift
fails the build.

- Artifacts audited: **64**
- Overall recall: **81.8%**
- Artifacts with a recognised attribute but no readable value: **8** (these become UNRESOLVED, never 'no premise')
- Prompt-injection artifacts in the set: **4** (the parser has no instruction surface, so they yield nothing)

## Confusion matrix

| Class | Gold | Correct | Wrong value | Missed | Spurious | Recall | Precision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `numeric:currency` | 4 | 4 | 0 | 0 | 0 | 100.0% | 100.0% |
| `numeric:percentage` | 4 | 4 | 0 | 0 | 0 | 100.0% | 100.0% |
| `numeric:quantity` | 8 | 8 | 0 | 0 | 0 | 100.0% | 100.0% |
| `temporal:absolute-duration` | 24 | 16 | 0 | 8 | 0 | 66.7% | 100.0% |
| `temporal:relative-date` | 4 | 4 | 0 | 0 | 0 | 100.0% | 100.0% |

## ⚠ Worst-performing class

**`temporal:absolute-duration` — recall 66.7%** (16/24 correct, 8 missed).

Decisions resting on this class are marked `unresolved` by `mark_coverage()` while recall is under 80%. The auditor may mark a decision unresolved; it may never mark one safe.

Under-covered classes (recall < 80%): `temporal:absolute-duration`

## What these numbers do and do not mean

**They measure this parser against this corpus.** The artifacts and the
extraction lexicon were written by the same author, so a recall of 1.0
would have meant nothing. The corpus therefore includes phrasings the
lexicon was deliberately not built around — spelled-out numerals, unlisted
synonyms such as "turnaround" and "cycle time", and values referred to
but stated elsewhere. The misses below are real misses of this parser.

**They say nothing about real supplier email.** No claim is made that this
distribution resembles production text.

> **No real Vertex AI call has ever been made in this repository.** No GCP
> credentials existed in the build environment. Extraction here is fully
> deterministic and needs no model, so these numbers are genuine; anything
> reported about the T2 judgement path came from the scripted stub in
> `judgment/model.py` and is labelled as such.
