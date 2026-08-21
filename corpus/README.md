# The UNWIND corpus

**This data is synthetic.** It was produced entirely by `corpus/generate.py`. It
is not derived from, sampled from, anonymised from, or inspired by any real
company, supplier, contract, customer or transaction. Every name in it is
invented. No figure in it is a measurement of anything in the world.

It is committed to the repository, so a cold clone needs no generation step.

## What it is

One scenario, built completely: a supplier lead-time premise
(`supplier_K.lead_time_days = 11`) feeding quotes, purchase orders, an ad flight
and customer promises across six months of decisions.

| File | Contents |
| --- | --- |
| `data/claims.jsonl` | Every premise, including the hub claim `clm_000000` |
| `data/conclusions.jsonl` | Every decision, with its premise edge set |
| `data/reverse_index.jsonl` | Direct (one-hop) claim → conclusion edges |
| `data/radius_truth.jsonl` | **Eval ground truth**: the hub's transitive closure with true depths and materiality |
| `data/sources.jsonl` | Sources and their authority scopes |
| `data/adversarial/` | One forged retraction. Stored, never processed. |
| `data/stats.json` | Everything measured below |
| `data/MANIFEST.sha256` | Per-file digests; how determinism is proven |

`reverse_index.jsonl` holds **direct edges only**, every row at `depth: 1`. The
transitive closure is deliberately *not* precomputed into it — precomputing it
would let the demo skip the traversal it exists to demonstrate. The closure
lives in `radius_truth.jsonl` as eval ground truth, which is a different thing
serving a different purpose.

## How materiality is computed

Every conclusion in the radius committed some lead time downstream. Its buffer
against the physical supplier constraint is `committed_lead_days - 11`. The
retraction moves the premise 11 → 20, a shock of +9 days. So:

```
material  <=>  9 > (committed_lead_days - 11)  <=>  committed_lead_days < 20
```

That is arithmetic, which is why it is a T1 rule and needs no model.

`committed_lead_days` is drawn from a two-component mixture, because commitments
genuinely are two populations rather than one spread:

- **Tight** (5% of commitments) — expedited and just-in-time work, priced off the
  supplier's real lead time with days of margin. Safety factor `U(1.05, 1.85)`.
- **Loose** (95%) — standard commercial terms. Lognormal with median safety
  factor `30/11`, anchored on the "ships within 30 days" boilerplate that
  dominates enterprise terms.

**[ASSUMPTION]** The 5% tight share is the assumption that carries the whole
result. It rests on expedited orders being a small minority of enterprise order
volume, because they carry premium freight cost. Change it and the die-back
changes — that is the honest behaviour, and it is why the generator *reports*
the die-back rather than asserting a target for it.

**[ASSUMPTION]** Buffer is drawn independently of depth: an internal handoff is
modelled as adding no buffer of its own. This makes deep dependents no safer
than shallow ones, which is the conservative direction.

A commitment that already closed out — delivery made, quote expired, flight
ended — before the retraction cannot be harmed by it, whatever its buffer was.
So `live material` is the stricter and more useful count:
`material AND closes_at > retraction_date`. Both are reported, because
conflating them would overstate the demo.

## Measured properties

Produced by `make corpus`; reproduce with `make corpus-verify`. Every number
here is read out of `data/stats.json`, which the generator wrote.

| Property | Measured |
| --- | --- |
| Claims | 1,083 |
| Conclusions | 4,004 |
| Reverse-index edges | 10,192 |
| Sources | 10 |
| Hub claim direct dependents | 882 |
| Hub claim **transitive** dependents (the blast radius) | 2,594 |
| Max premise-chain depth | 5 |
| Radius scoreable arithmetically | 2,420 (4 are unresolvable) |
| Material by buffer arithmetic | 117 |
| **Die-back** | **95.165 %** |
| Live material survivors (also still open at the retraction) | 78 |
| — not escaped | 28 |
| — escaped | 50 |
| Material but already closed out | 39 |
| Median decision → retraction gap, whole radius | 91 days |
| Median escape → retraction gap | 63.5 days (range 0–181) |
| **Escaped survivors decided ≥120 days before the retraction** | **12** |
| Deliberately UNRESOLVED conclusions | 4 |
| Adversarial artifacts | 1, unprocessed |

Depth histogram: 712 at depth 1, 1,088 at 2, 424 at 3, 150 at 4, 50 at 5.

### The temporal gap

This is what the long-dated instruments were added for. Of the 50 escaped
survivors, the distribution of how long each had been standing before its
premise moved:

| Decision → retraction | Escaped survivors |
| --- | --- |
| 0–30 days | 13 |
| 30–60 | 10 |
| 60–90 | 9 |
| 90–120 | 6 |
| 120–150 | 2 |
| 150–183 | 10 |

**12 escaped survivors had been standing for 120 days or more**, the oldest for
182 days — decided on the first day of the window, still governing on the last.
11 of those 12 are long-dated instruments, which is the amendment doing exactly
the work it was added for.

### What the long-dated instruments contributed

| | Count |
| --- | --- |
| `standing_price` | 130 |
| `framework_promise` | 150 |
| `long_lead_order` | 140 |
| — of which materially harmed | 23 |
| — of which escaped survivors | 21 |
| — of which escaped survivors at ≥120 days | 11 |

### Where the measurements differ from the specification

Stated plainly rather than tuned away:

- **Die-back 95.165 % against a ≈96 % target.** It moved by 0.135 points when
  the long-dated instruments were added, because those instruments draw from the
  same 0.05 tight/loose mixture as everything else. The new number stands; it was
  not tuned back.
- **78 live material survivors against an original ~31 target.** That target was
  withdrawn as arithmetically inconsistent with a ≈96 % die-back over a ~2,000
  radius. 2,594 → 78 is a 97.0 % cull.
- **Escaped/not-escaped is 48/30.** In the first corpus this ratio was inverted
  (25 escaped / 30 not). The long-dated instruments corrected it as a side
  effect rather than by design: a published price list or a countersigned
  framework agreement has left the building almost by definition, so their high
  escape probability is a property of the instrument, not a thumb on the scale.

### What is assigned rather than emergent

Three conclusions in the escaped live-material set have their reversibility
**assigned deterministically**, so the demo is guaranteed one of each class
rather than depending on a lucky draw:

| Conclusion | Reversibility | Effect |
| --- | --- | --- |
| `cnc_000079` | idempotent | re-issuing the corrected quote converges |
| `cnc_001762` | compensable | ad flight, USD 41,800.00 partially creditable |
| `cnc_002416` | irreversible | expedite premium paid, USD 12,650.00, non-refundable |

Those two money figures are invented parameters of the synthetic scenario. They
are not estimates of anything.

## The adversarial artifact

`data/adversarial/forged_retraction.json` is an email from Zenith Freight
Brokerage asserting that Kestrel's lead time is now 34 days. Zenith holds
authority over `freight_broker_Z.` and nothing else; the hub claim's
`authority_scope` names only `src_supplier_K` and `src_msa_K`. It therefore has
no standing, and accepting it would cascade a mass unwind of 2,594 real
commitments off a forged input.

**It is stored and not processed by the generator.** Task 2's authority gate now refuses it deterministically — see `make cascade-forged`.

**It leaks into nothing.** It appears in no `.jsonl` file — not in
`claims.jsonl`, not in `conclusions.jsonl`, not in `reverse_index.jsonl`. Task 3
feeds it to the authority gate, which must refuse it deterministically.

## Determinism

`corpus/generate.py` uses a single seeded `random.Random(20260831)`, iterates in
sorted order throughout, and writes JSON with sorted keys. No wall-clock time is
read; every timestamp derives from a fixed window start.

```
make corpus-verify     # regenerates into a temp dir, diffs MANIFEST.sha256
```

Verified: the regenerated manifest is byte-identical to the committed one.
