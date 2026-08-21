"""`python -m command_os.cli`: run one mission from a terminal.

Exists so a judge can watch the whole thing without a browser, a credential,
or a Google Cloud account -- the same "nothing here needs a GCP account"
promise the rest of the repository keeps. `principal` is required, as it is
everywhere else; the CLI supplies the invoking OS user rather than inventing
one, and labels it as such.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Agentic Command OS mission.")
    parser.add_argument(
        "objective",
        nargs="?",
        default=None,
        help="mission objective; changes the plan (try 'Trace the impact of a changed premise')",
    )
    parser.add_argument(
        "--require-approval",
        action="store_true",
        help="pause at the Human Override Gate instead of concurring at launch",
    )
    args = parser.parse_args(argv)

    from command_os.mission import DEFAULT_OBJECTIVE, run_mission

    principal = f"human::{os.environ.get('USER') or getpass.getuser()}@localhost"
    result = run_mission(
        args.objective or DEFAULT_OBJECTIVE,
        principal=principal,
        auth_method="cli",
        auto_approve=not args.require_approval,
        allow_model=False,
    )

    plan = result.plan or {}
    print(f"\nOBJECTIVE  {result.objective}")
    print(f"CLASS      {plan.get('objective_class')}   PLANNER {plan.get('provenance')}")
    print(f"PRINCIPAL  {principal}\n")
    for stage in result.stages:
        print(f"  {stage.n:2d} [{stage.status:<22}] {stage.name}")
        print(f"       {stage.summary}")
    if result.report:
        print(f"\nSTATUS  {result.report.status}")
        for field, value in result.report.model_dump().items():
            if field in {"objective", "status", "case_ids"}:
                continue
            print(f"  {field:26s} {value}")
    return 0


if __name__ == "__main__":  # pragma: no cover -- entry point
    sys.exit(main())
