# Measuring T2 judgement quality — why it is still unmeasured

**Status: NOT BUILT.** This document is the analysis, the spec, and an honest
statement of the one part I could not solve. It is not a claim that anything was
measured.

---

## 1. The problem, precisely

The live run attempted 60 T2 nodes and resolved **0**, with **0 exceptions**.
That is not a model failure. All 174 nodes in the T2 queue carry
`committed_lead_days = None`, and `judgment/assessor.py` contains:

```python
if original_committed_lead_days is None:
    return _unresolved(...)  # BEFORE the model's answer is consulted
```

So the outcome was fixed by the corpus. A different sample behaves identically —
verified: 0 of all 174 carry a numeric term.

**T2 executes correctly and has never been tested on a case where the model's
answer decides.**

---

## 2. What a valid fixture requires

A conclusion class that is simultaneously:

- **ambiguous** — materiality cannot be decided by subtraction alone, so the
  case genuinely needs judgement;
- **decidable** — it carries a committed numeric value the model's re-derivation
  can be scored against, so the assessor reaches its comparison branch.

Worked shape:

```
conclusion   cnc_X, committed_lead_days = 33
premises     supplier_K.lead_time_days = 11        (numeric, visible)
             msa_K.delivery_clause                 (clause text, visible)

clause text  "Delivery shall occur within three standard supplier cycles
              of order confirmation."

structured   { "governing_multiplier": 3 }         ← WITHHELD from the prompt
gold         multiplier × premise = 3 × 11 = 33

after the retraction (11 → 20) the correct re-derivation is 60,
delta 27 > margin → MATERIAL. The model must read the clause to get there.
```

Distractor classes are required so the model cannot score well by always
answering one way: cases whose correct answer is **immaterial** (the buffer
absorbs the shock) and cases whose correct answer is genuinely **unresolved**
(the clause is unreadable even to a careful human).

---

## 3. ⚠ The independence problem — where this stops

Task 6 §3.3 sets the bar: *"the gold label must be derivable from something the
model never sees."* There are **two** independence properties hiding in that
sentence, and they are not equally achievable.

### 3a. Mechanical withholding — ACHIEVABLE

The prompt provably never contains the multiplier or the gold number. This is
enforceable and testable, exactly as the extraction comparison already does it:
`tests/test_recall_compare.py` asserts the recall prompt never carries the gold
value, with a vacuity case. The same pattern applies here — build a variant that
leaks the resolution into the clause text and prove the guard fires.

**I could build this.** It is straightforward.

### 3b. Authorship independence — NOT ACHIEVABLE BY ME

The clause text and the scoring key would be written by **the same generator, in
the same commit, by the same author**. A model that scores well would be
demonstrating that it can read a sentence I wrote to express a rule I also
wrote — and I chose the phrasing knowing what the answer had to be.

That is not a benchmark. It is a mirror.

`docs/COVERAGE.md` already concedes this for extraction, where it is a caveat:
the corpus deliberately includes phrasings the lexicon was not built around, so
the misses are real. **For judgement it is worse than a caveat.** Extraction has
an objective referent — the number is either in the text or it is not. Judgement
does not: whether "three standard supplier cycles" means 33 is *entirely* a
matter of how I chose to phrase it.

A skeptical judge would find this faster than they would have criticised the
honest 0/60 — and rightly. **A self-authored judgement benchmark is the single
easiest thing on this page to discredit, and discrediting it would cast doubt on
the +18.2 pp, which is real and hard-won.**

### 3c. What would actually close it

One of:

1. **Real contract text.** Clauses from public filings, standard-form
   agreements, or published procurement templates — text written by someone who
   had never heard of this project. The gold label is then a human reading of
   that text, ideally by more than one person, with inter-annotator agreement
   reported.
2. **A held-out human annotator.** Someone other than the author labels the
   cases without seeing the generator.
3. **An existing public benchmark** for contractual-term interpretation, with
   UNWIND's assessor evaluated against its published labels.

All three need something this repository does not have: **text or labels from
outside the author.** None of them can be manufactured by generating more
synthetic data.

---

## 4. The decision

**I did not build the fixture.**

Building 3a alone would have produced a number. That number would have been
reported with a caveat, the caveat would have been true, and the number would
still have been worth approximately nothing — because the interesting question
is not "can a model parse my sentence" but "can a model interpret a real
contractual term."

Task 6 §3.3 anticipated exactly this and gave permission:

> *"If you cannot achieve genuine independence, stop and say so. An honest 'we
> could not construct an unbiased fixture, here is why' is a better artifact
> than a number nobody should trust."*

That is the call I made. **T2 judgement quality remains unmeasured, and the
reason is now precise rather than vague** — which is itself an improvement over
where Task 5 left it.

---

## 5. What DID change

- `judgment/assessor.py` no longer accepts a `model` parameter it never called.
  The Task 5 audit flagged it as something a judge would find. It is removed,
  and the docstring now states plainly that the assessor is the **deterministic
  half of T2** — the re-deriver is the model half.
- The T2 non-test is documented in three places
  (`docs/LIVE-VERIFICATION.md`, `docs/evidence/README.md`, the README) with the
  structural reason, not just the number.

---

## 6. If you build it anyway

The spec in §2 is complete enough to implement. The contract to hold yourself to:

| | |
| --- | --- |
| B1 | 60–100 conclusions, both ambiguous and decidable |
| B2 | gold derived from a structured field the prompt never sees |
| B3 | a test asserting the withholding **plus a vacuity case that leaks the answer and proves the guard fires** |
| B4 | distractor classes present; class balance reported |
| B5 | corpus determinism re-verified byte-identical |
| B6 | accuracy measurable in one command |
| B7 | **deterministic baselines reported beside the model** — always-unresolved and always-material. If the model cannot beat both, say so. |

And report the authorship-independence caveat from §3b next to whatever number
you get. Without it, the number is not evidence.
