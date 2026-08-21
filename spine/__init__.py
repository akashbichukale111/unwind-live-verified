"""The deterministic spine: T0 structural traversal and T1 arithmetic scoring.

NOTHING IN THIS PACKAGE MAY IMPORT A MODEL CLIENT, DIRECTLY OR TRANSITIVELY.
That is not a style rule -- it is the tiered-degradation guarantee expressed as
a package boundary, and `tests/test_zero_model.py` walks the import graph to
enforce it. If a future change needs judgement rather than arithmetic, it
belongs in an agent, not here.
"""
