"""T2: the tier that judges rather than computes.

EVERYTHING IN THIS PACKAGE MAY BE WRONG, AND MUST BE WRONG SAFELY.

`spine/` is arithmetic and traversal; being wrong there is a bug. Here, being
wrong is expected -- these are readings of clauses, reconciliations of
differently-worded claims, judgements about whether a conclusion actually
changed. So every module in this package obeys the same three rules:

1. When the model is unavailable, the answer is UNRESOLVED. Never a guess, never
   a silent fallback to "unaffected".
2. Nothing here decides alone. T2 proposes; the deterministic gates in `spine/`
   dispose.
3. Judgement is tuned to UNDER-report. A missed correction leaves a wrong
   decision operating, which is the status quo. An invented correction reaches a
   counterparty and un-says something true, which is worse than the disease.

⚠ NO REAL VERTEX CALL HAS EVER BEEN MADE FROM THIS PACKAGE. No GCP credentials
existed in the build environment. The Vertex path is written and unproven; every
measured number in the repository comes from the scripted model in
`judgment/model.py`, which is labelled as such wherever it is reported.
"""
