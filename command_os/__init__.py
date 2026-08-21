"""Agentic Command OS: the master orchestration layer above UNWIND's six
existing control layers (spine/court/judgment, warrant/, tower/,
countersign/, hyperion/, singularity/).

THIS PACKAGE CONTAINS NO NEW DECISION LOGIC
--------------------------------------------
`command_os/mission.py` sequences calls into engines that are already real
and already live one layer down -- `singularity.genome.compute_genome`,
`singularity.behavior.detect_drift`, `hyperion.guard.evaluate_with_hyperion`
(which itself is a read-only wrapper around `tower.gateway.evaluate_gateway`),
and `warrant.ledger`/`countersign.verify` for the repair-and-remint path.
Nothing here re-implements a check that already exists; this package's only
job is to run one mission through the existing engines, in order, and
narrate what each one actually returned. See `command_os/mission.py`'s
module docstring for the one place a scripted (labelled) input enters.
"""

from __future__ import annotations
