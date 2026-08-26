"""Trajectory evaluation and governed agent evolution.

Two things live here, and the boundary between them is deliberate:

  `criteria.py` / `trajectory.py`  -- PURE. No I/O, no clock beyond an
      explicitly-passed `now`, no model client. Scoring a mission is a
      function of what the mission measured, so it can be recomputed by
      anyone from the persisted record.

  `store.py` / `propose.py` / `promote.py`  -- the governed loop: persistence,
      candidate generation, and the gates that stand between a candidate and
      production.

`tests/test_evolution_zero_model.py` walks the import graph of the pure side
the same way `tests/test_warrant_zero_model.py` walks `warrant/`.
"""
