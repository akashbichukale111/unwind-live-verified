.DEFAULT_GOAL := help
SHELL := /bin/bash
PY := .venv/bin/python
PIP := uv pip install --python .venv/bin/python

FIRESTORE_EMULATOR_HOST ?= localhost:8080
export FIRESTORE_EMULATOR_HOST

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.venv:
	uv venv --python 3.12 .venv

.PHONY: install
install: .venv ## Install runtime + dev dependencies into .venv
	$(PIP) -e ".[dev]"

.PHONY: emulator
emulator: ## Start the Firestore emulator in the foreground (needs Java 11+)
	./infra/emulator.sh

.PHONY: dev
dev: ## Run the API against the Firestore emulator + in-process Pub/Sub shim
	./infra/dev.sh

.PHONY: test
test: ## Run the test suite
	$(PY) -m pytest -q

.PHONY: redteam
redteam: ## Run the 20-attack red-team suite and record the log under evidence/
	@mkdir -p evidence/redteam
	$(PY) -m pytest tests/test_adversarial.py -v -p no:warnings \
	  | tee "evidence/redteam/redteam-$$(date -u +%Y%m%dT%H%M%SZ).log"

.PHONY: mission
mission: ## Run one mission end to end against the emulator, zero-model
	@UNWIND_VERTEX_DISABLED=1 UNWIND_COUNTERSIGN_SIMULATED=1 \
	  $(PY) -m command_os.cli

.PHONY: causality
causality: ## THE falsification test: same mission, evidence with and without the escalation
	$(PY) -m pytest tests/test_mission_causality.py -v -p no:warnings

.PHONY: lint
lint: ## Lint and format-check
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

.PHONY: corpus
corpus: ## Regenerate the committed corpus (output must be byte-identical)
	$(PY) -m corpus.generate --out corpus/data

.PHONY: corpus-verify
corpus-verify: ## Prove the generator is deterministic (regenerate + diff manifest)
	$(PY) -m corpus.generate --verify --out corpus/data

.PHONY: verify-models
verify-models: ## Verify the four Google models against a REAL project (credit-safe)
	@echo "Requires: gcloud auth application-default login"
	@echo "Text models only. Add --media to spend credits on ONE Veo + ONE Lyria generation."
	$(PY) scripts/verify_models.py $(ARGS)

.PHONY: eval
eval: ## Run the eval harness over evals/scenarios
	$(PY) -m evals.harness --scenarios evals/scenarios --out evals/results

.PHONY: eval-vertex-off
eval-vertex-off: ## THE GUARANTEE: full cascade with Vertex disabled. Required in CI.
	UNWIND_VERTEX_DISABLED=1 $(PY) -m evals.harness \
		--scenarios evals/scenarios --out evals/results --quiet

.PHONY: cascade
cascade: ## Run one cascade from the committed corpus and print the four regimes
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m spine.cli cascade

.PHONY: cascade-forged
cascade-forged: ## Run the forged retraction. The authority gate must refuse it.
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m spine.cli cascade \
		--source src_broker_Z --new-value 34 --reason "broker notice"

.PHONY: coverage
coverage: ## Audit extraction recall; rewrite docs/COVERAGE.md
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m judgment.cli coverage

.PHONY: sentinel
sentinel: ## Sweep for premises nobody has reaffirmed (silence, not change)
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m judgment.cli sentinel

.PHONY: t2
t2: ## Run the T2 queue over what T1 refused (scripted model unless --vertex)
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m judgment.cli t2

.PHONY: adversarial
adversarial: ## Both attacks: the obvious forgery and the partial-authority overreach
	@echo "=== 1. OBVIOUS FORGERY: a freight broker retracting a supplier fact ==="
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m spine.cli cascade \
		--source src_broker_Z --new-value 34 --reason "broker notice"
	@echo ""
	@echo "=== 2. PARTIAL AUTHORITY: a legitimate source reaching one step outside ==="
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m spine.cli cascade \
		--source src_msa_K --new-value 45 \
		--reason "Executed amendment No.4 to the master supply agreement"

.PHONY: debt
debt: ## Score standing causal debt -- what UNWIND shows on a normal day
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m spine.cli debt

.PHONY: court
court: ## Run the repair court over the hub cascade and print the JSON report
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m settle.cli settle

.PHONY: obligation
obligation: ## Render ONE full correction obligation -- the product's actual output
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m settle.cli obligation --pick cnc_001211

.PHONY: multi-premise
multi-premise: ## Two premises failing at once: radii merge, arbiter allocates
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m settle.cli settle \
		--also-claim clm_000115 --also-source src_supplier_L --also-new-value 26

.PHONY: golden
golden: ## Deterministic court transcript; CI fails if it drifts from the committed copy
	@UNWIND_VERTEX_DISABLED=1 $(PY) -m settle.cli golden --out evals/golden/court.txt

.PHONY: ui
ui: ## Serve the operator field at http://127.0.0.1:8000 (no credentials needed)
	@UNWIND_VERTEX_DISABLED=1 UNWIND_OTEL_CONSOLE=0 \
		.venv/bin/uvicorn services.api.main:app --host 127.0.0.1 --port 8000

.PHONY: ui-check
ui-check: ## Drive the UI in a real browser: measure fps, capture screens, assert
	@$(PY) scripts/measure_ui.py

.PHONY: contrast
contrast: ## Recompute every colour pair; fail below 4.5:1
	@$(PY) scripts/check_contrast.py

.PHONY: deploy-check
deploy-check: ## Preflight the deploy with NO credentials. Fails loudly and specifically.
	@$(PY) scripts/deploy_check.py

.PHONY: deploy-verify
deploy-verify: ## Prove a deployed service COMPUTES, not merely renders. URL=https://...
	@$(PY) scripts/deploy_verify.py "$(URL)"

.PHONY: verify-live
verify-live: ## ⚠ NEEDS CREDENTIALS. Real Vertex call + recall comparison + T2. Writes docs/LIVE-VERIFICATION.md
	@$(PY) scripts/verify_live.py

.PHONY: deploy
deploy: ## ⚠ NEEDS CREDENTIALS. Deploy to Cloud Run. Run deploy-check first.
	@./infra/deploy.sh

.PHONY: vertex-check
vertex-check: ## ONE real Vertex call. Prints the raw response or the exact failure.
	@$(PY) scripts/vertex_check.py

.PHONY: smoke
smoke: ## Run the throwaway ADK smoke agent (requires Vertex credentials)
	$(PY) -m agents.smoke.run

.PHONY: web-ui
web-ui: ## Launch `adk web` for local tracing during development
	.venv/bin/adk web agents

# The JSON-emitting targets above are silenced with @ so their output pipes
# into jq without make's own recipe echo corrupting it.

# ---------------------------------------------------------------------------
# Not built. Fails loudly rather than printing a fake pass.
# ---------------------------------------------------------------------------
.PHONY: demo
demo: ## [NOT BUILT - Task 5] End-to-end cascade demo
	@echo "make demo: NOT BUILT."
	@echo "The end-to-end cascade demo is scheduled for Task 5, with the field"
	@echo "visualisation and the timestamped run. The court and the obligation it"
	@echo "produces ARE built -- see 'make court', 'make obligation', 'make golden'."
	@echo "Failing loudly on purpose."
	@exit 1

