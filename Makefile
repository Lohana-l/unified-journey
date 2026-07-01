# Tessera CDP : build / run / test automation.
# Run `make help` to see every target with its description.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ---------------- Environment ----------------
PYTHON ?= python3.11
VENV   ?= .venv
PIP    := $(VENV)/bin/pip
PY     := $(VENV)/bin/python

DBT_PROFILES_DIR := dbt
DUCKDB_PATH      ?= warehouse/tessera.duckdb

# ---------------- Meta targets ----------------
.PHONY: help
help:  ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "; printf "\n\033[1mTessera CDP : available targets\033[0m\n\n"} \
	    /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""

# ---------------- Setup ----------------
.PHONY: install
install:  ## Create venv, install all dev dependencies, bootstrap dbt profile.
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt
	$(PY) -m pip install -e .
	@# Crée le profil dbt local s'il n'existe pas (le .example ne contient
	@# aucun secret : tout passe par des env vars avec défauts MinIO).
	@test -f dbt/profiles.yml || cp dbt/profiles.yml.example dbt/profiles.yml
	@echo "dbt/profiles.yml prêt."
	@echo "Run 'source $(VENV)/bin/activate' to enter the venv."

.PHONY: dbt-deps
dbt-deps:  ## Install dbt packages (dbt_utils, dbt_expectations).
	cd dbt && DBT_PROFILES_DIR=. "$(PWD)/$(VENV)/bin/dbt" deps

# ---------------- Infrastructure ----------------
.PHONY: up
up:  ## Start MinIO + Streamlit (default). Tip: make up-full for + Kestra.
	docker compose up -d
	@echo ""
	@echo "  MinIO console : http://localhost:9001  (minioadmin / minioadmin)"
	@echo "  Streamlit     : http://localhost:8501"
	@echo ""
	@echo "  Astuce : 'make up-full' démarre aussi Kestra (orchestration)."
	@echo ""

.PHONY: up-full
up-full:  ## Start full stack including Kestra orchestrator.
	docker compose --profile full up -d
	@echo ""
	@echo "  MinIO console : http://localhost:9001  (minioadmin / minioadmin)"
	@echo "  Kestra UI     : http://localhost:8080"
	@echo "  Streamlit     : http://localhost:8501"
	@echo ""

.PHONY: down
down:  ## Stop the stack (keeps volumes).
	docker compose --profile full down

.PHONY: nuke
nuke:  ## Stop the stack AND delete all data volumes. Irreversible.
	docker compose --profile full down -v
	rm -f $(DUCKDB_PATH)
	rm -rf data/bronze data/silver data/gold

# ---------------- Pipeline ----------------
.PHONY: seed
seed:  ## Generate synthetic demo events (offline fallback for all 4 sources).
	$(PY) -m seed.generate_sample_data

.PHONY: ingest
ingest:  ## Run the 4 ingestion extractors -> Parquet in MinIO bronze.
	$(PY) -m ingestion.main --all

.PHONY: transform
transform: dbt-deps  ## Run dbt build (staging -> intermediate -> marts + tests).
	@start=$$SECONDS; \
	( cd dbt && DBT_PROFILES_DIR=. "$(PWD)/$(VENV)/bin/dbt" build ); rc=$$?; \
	if [ $$rc -eq 0 ]; then st=success; else st=failed; fi; \
	$(PY) -m ingestion.record_run --pipeline dbt --step build --status $$st --duration-ms $$(( (SECONDS - start) * 1000 )) || true; \
	exit $$rc
# (recette ci-dessus) lance dbt build, mémorise le code retour, puis enregistre un run d'audit
#   'dbt' (succès/échec + durée) pour que le dashboard voie la transformation.

.PHONY: quality
quality:  ## Run Soda Core data quality checks.
	@start=$$SECONDS; \
	$(PY) -m soda scan -d tessera -c quality/soda/configuration.yml quality/soda/checks.yml; rc=$$?; \
	if [ $$rc -eq 0 ]; then st=success; else st=failed; fi; \
	$(PY) -m ingestion.record_run --pipeline soda --step "soda scan" --status $$st --duration-ms $$(( (SECONDS - start) * 1000 )) || true; \
	exit $$rc
# (recette ci-dessus) lance le scan Soda, mémorise le code retour, puis enregistre un run d'audit
#   'soda' ; un scan en échec apparaît alors comme alerte Soda dans le dashboard.

.PHONY: pipeline
pipeline: seed ingest transform quality  ## Full end-to-end run: seed -> ingest -> transform -> quality.

# ---------------- App ----------------
.PHONY: app
app:  ## Run the Streamlit dashboard locally with auto-reload (without Docker).
	$(VENV)/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0

# ---------------- Quality gates ----------------
.PHONY: lint
lint:  ## Run ruff + sqlfluff on Python and SQL.
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	cd dbt && "$(PWD)/$(VENV)/bin/sqlfluff" lint models --dialect duckdb || true

.PHONY: format
format:  ## Auto-format Python and SQL.
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .
	cd dbt && "$(PWD)/$(VENV)/bin/sqlfluff" fix models --dialect duckdb || true

.PHONY: test
test:  ## Run pytest unit tests.
	$(VENV)/bin/pytest -v tests/

.PHONY: dbt-compile
dbt-compile: dbt-deps  ## dbt compile only (CI-friendly, no DB needed).
	cd dbt && DBT_PROFILES_DIR=. "$(PWD)/$(VENV)/bin/dbt" compile

.PHONY: ci
ci: lint test dbt-compile  ## Run everything CI runs (no infra required).

# ---------------- Utilities ----------------
.PHONY: clean
clean:  ## Remove caches, build artefacts, dbt target.
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf dbt/target dbt/dbt_packages dbt/logs
	rm -rf build dist *.egg-info

# ---------------- Benchmarks ----------------
.PHONY: benchmark benchmark-quick
benchmark:  ## Full pipeline benchmark (seed + ingest + transform + quality).
	$(PY) scripts/benchmark.py

benchmark-quick:  ## Quick benchmark (skip Soda quality checks).
	$(PY) scripts/benchmark.py --quick
