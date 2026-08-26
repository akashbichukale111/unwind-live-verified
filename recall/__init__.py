"""Recall: what UNWIND knows because a previous mission measured it.

Four modules, one direction of flow:

    mission finishes
      -> `recall/distill.py`   one atomic fact per thing measured
      -> `recall/store.py`     append-only, content-addressed, provenanced
      -> `recall/index.py`     filter, score, BOUND -- never load everything
      -> `recall/guard.py`     the one-way valve: scrutiny only, never scope
      -> next mission's plan

`recall/guard.py` is the module to read first. It is what makes this a
knowledge engine rather than a persistence surface for an attacker.
"""

__all__: list[str] = []
