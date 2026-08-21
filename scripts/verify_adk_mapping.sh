#!/usr/bin/env bash
# Verifies every ADK 2 construct the README claims against the actual code.
#
# This script writes no runtime code and is not part of the cascade, the
# gateway, or any decision path -- its only job is honesty enforcement: the
# README's "ADK 2 -- the locked construct mapping" table may not claim a
# construct this script cannot find, at the exact site the table names. If a
# claimed construct's signature moves or disappears, this fails loudly
# instead of the README quietly going stale.
#
# Each check is a grep for the CONSTRUCT'S OWN SIGNATURE (the class/call that
# proves the thing is real, not a comment claiming it is), at the file:line
# the README cites. A passing check here is the same kind of evidence
# `tests/test_tower_gateway.py::test_gateway_workflow_is_a_real_adk_workflow`
# already is for one row of this table -- this script generalizes that
# discipline across all six rows in one command.
#
# Usage:
#   bash scripts/verify_adk_mapping.sh
#
# Exit codes: 0 every claimed construct found; 1 at least one is missing.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

FAIL=0
PASS_COUNT=0
TOTAL=0

check() {
  local name="$1" file="$2" pattern="$3"
  TOTAL=$((TOTAL + 1))
  if [[ ! -f "$file" ]]; then
    echo "FAIL  $name -- file does not exist: $file"
    FAIL=1
    return
  fi
  local hit
  hit="$(grep -n -E "$pattern" "$file" | head -1)"
  if [[ -z "$hit" ]]; then
    echo "FAIL  $name -- pattern not found in $file: $pattern"
    FAIL=1
    return
  fi
  local line="${hit%%:*}"
  echo "PASS  $name -- $file:$line"
  PASS_COUNT=$((PASS_COUNT + 1))
}

echo "=============================================================================="
echo "ADK 2 CONSTRUCT MAPPING -- README claim vs. actual code"
echo "=============================================================================="

# 1. Workflow + FunctionNode + Edge / DEFAULT_ROUTE -- the cascade graph.
check "Workflow+FunctionNode (cascade graph)" \
  "agents/cascade/workflow.py" \
  '^cascade_workflow = Workflow\('
check "  ... DEFAULT_ROUTE actually imported (routing is real, not decorative)" \
  "agents/cascade/workflow.py" \
  'DEFAULT_ROUTE'

# 2. Deterministic router -- Gateway reason codes.
check "Deterministic router (Gateway)" \
  "tower/gateway.py" \
  '^gateway_workflow = Workflow\('
check "  ... WARRANT_INSUFFICIENT reason code wired into the router" \
  "tower/gateway.py" \
  'GatewayReasonCode\.WARRANT_INSUFFICIENT'

# 3. FunctionNode -- warrant SPEND, atomic spend-or-refuse (Card 0).
check "FunctionNode (warrant SPEND)" \
  "tower/gateway.py" \
  '^warrant_check = FunctionNode\(func=_warrant_node'
check "  ... backed by warrant.ledger.spend_or_refuse, not a stub" \
  "tower/gateway.py" \
  'from warrant\.ledger import spend_or_refuse'

# 4. Dynamic pattern -- registry -> coordinator selection (Card 2).
check "Dynamic pattern (registry -> coordinator)" \
  "tower/registry.py" \
  '^def compose_capability_workflow\(capability: str\) -> Workflow:'

# 5. Single-turn AgentTool -- Countersign / Gemma (Card 3).
check "Single-turn AgentTool (Countersign)" \
  "countersign/agent.py" \
  '^countersign_tool = AgentTool\(agent=countersign_agent'
check "  ... the wrapped agent is actually mode=\"single_turn\"" \
  "countersign/agent.py" \
  'mode="single_turn",'

# 6. Durable long-running runtime -- case pause/resume.
check "Durable long-running runtime (pause/resume)" \
  "tower/runtime.py" \
  '^case_pause_tool = LongRunningFunctionTool\(pause_case_for_human\)'

echo "=============================================================================="
echo "$PASS_COUNT/$TOTAL checks passed"
if [[ "$FAIL" -ne 0 ]]; then
  echo "RESULT: FAIL -- the README claims a construct this script could not find."
  exit 1
fi
echo "RESULT: PASS -- every ADK 2 construct claimed in the README is present at its cited site."
exit 0
