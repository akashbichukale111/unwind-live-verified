# The retraction feed

**One page. This is the part that makes UNWIND a protocol rather than a product.**

Everything else in this repository assumes the failing premise is *yours* — a
supplier email your system ingested, an ERP row your system wrote. But the
supplier already knows their lead time changed. The regulator already published
the amended rule. Today that knowledge reaches you as a PDF somebody reads three
weeks later, and the gap between "the world changed" and "we noticed" is where
every correction obligation in this repo comes from.

A retraction feed closes that gap by letting the party who owns a fact publish
its death directly.

## The shape

A publisher emits **retractions**, not facts. One retraction says: *this claim,
which I previously asserted, is no longer true as of this instant, and here is
what replaces it.*

```json
{
  "canonical":       "supplier_K.lead_time_days",
  "publisher":       "did:web:supplier-k.example",
  "previous_value":  11,
  "new_value":       20,
  "valid_from":      "2026-07-06T09:00:00Z",
  "invalidated_at":  "2026-07-06T09:00:00Z",
  "reason":          "production line requalification",
  "authority_scope": ["supplier_K."],
  "signature":       "<detached signature over the canonical form>"
}
```

Every field is already in `lib/schema.py`. `canonical`, `valid_from`,
`invalidated_at`, `invalidation_reason` and `authority_scope` are the Temporal
Truth and retraction-authority fields Task 1 typed before any logic existed —
which is why this document is one page and not a redesign.

## Why `authority_scope` is the load-bearing field

A feed without it is an open microphone. UNWIND already refuses a retraction
from a source with no standing over the claim it targets — `make adversarial`
shows a freight broker's attempt to retract a supplier's lead time refused with
`source_outside_claim_scope`, radius zero. **The same gate is what makes a
public feed safe to subscribe to**: a subscriber consumes the feed and applies
its own authority policy, so a publisher can only kill facts it owns.

That is the whole security model, and it is deterministic. No model call, no
reputation heuristic, no allowlist to maintain.

## Transport

Pub/Sub, which the cascade already uses. A publisher writes to a topic; each
subscriber runs its own `spine.authority` gate on arrival, then its own cascade.
Nothing about the subscriber's graph is exposed to the publisher — the
publisher says only that a fact died, never who was standing on it.

`lib/idempotency.py` already covers the redelivery case: Pub/Sub is
at-least-once, and raising the same correction obligation twice means
apologising to the same customer twice.

## What a subscriber gets

```
retraction arrives  →  authority gate (T0, deterministic)
                    →  blast radius over the LOCAL reverse index
                    →  four regimes
                    →  correction obligations for the material-escaped cell
```

Identical to the flow a manually-entered retraction takes. The feed is an input,
not a second pipeline.

## Status

**[DESIGNED]** — the schema fields exist and are populated, the authority gate
is [BUILT] and tested, and the Pub/Sub transport is [BUILT]. What does not exist
is a published topic, a signature scheme, or a subscriber registry. No feed has
been published or consumed.

Nothing in this document is claimed as running code.

## The honest objection

A feed is only worth building if publishers adopt it, and a supplier has no
direct incentive to announce that their own commitment slipped. The realistic
first publishers are the ones whose facts are already public and already
machine-readable — regulators, standards bodies, exchange-rate and tariff
sources. Those are also the premises with the widest blast radius, because
everybody rests on them. That is where a feed would start, and it is a smaller
claim than "the industry adopts a standard".
