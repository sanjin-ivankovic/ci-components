# ============================================================================
# example-org/ci-components — shared GitLab CI/CD components hub
# ============================================================================
#
# Local developer entry point. CI is the authoritative gate (.gitlab-ci.yml);
# these targets give fast local feedback that mirrors the native CI jobs.
#
# Usage:
#   make help        - Show this help
#   make setup       - Install pre-commit hooks
#   make lint        - Lint YAML + Markdown + shell (reads .config/)
#   make test        - Run the .ci/scripts pytest suite
#   make validate    - lint + test (everything CI checks, locally)
#
# ============================================================================

.PHONY: help setup lint lint-yaml lint-markdown lint-shell test validate clean
.DEFAULT_GOAL := help

YAMLLINT_CONFIG      := .config/.yamllint
MARKDOWNLINT_CONFIG  := .config/.markdownlint-cli2.jsonc
SHELLCHECK_CONFIG    := .config/.shellcheckrc

# ----------------------------------------------------------------------------
# Help
# ----------------------------------------------------------------------------

help: ## Show this help message
	@echo "example-org/ci-components - Available Commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ----------------------------------------------------------------------------
# Setup
# ----------------------------------------------------------------------------

setup: ## Install pre-commit hooks (run once after cloning)
	@echo "Installing pre-commit hooks..."
	@pre-commit install
	@pre-commit install --hook-type commit-msg
	@echo "Done. Pre-commit hooks are now active."

# ----------------------------------------------------------------------------
# Lint (mirrors the native lint:* CI jobs, reading .config/ rule files)
# ----------------------------------------------------------------------------

lint: lint-yaml lint-markdown lint-shell ## Lint YAML + Markdown + shell

lint-yaml: ## Lint YAML (templates/, .ci/, .config/)
	@echo "Linting YAML..."
	@yamllint -c $(YAMLLINT_CONFIG) .

lint-markdown: ## Lint Markdown (README + docs)
	@echo "Linting Markdown..."
	@markdownlint-cli2 --config $(MARKDOWNLINT_CONFIG) "**/*.md" "#.archive"

lint-shell: ## Lint shell scripts under .ci/scripts/
	@echo "Linting shell scripts..."
	@find .ci/scripts -name '*.sh' -print0 | xargs -0 -r shellcheck --rcfile=$(SHELLCHECK_CONFIG)

# ----------------------------------------------------------------------------
# Test (the .ci/scripts pytest suite — same as the test:ci-scripts CI job)
# ----------------------------------------------------------------------------

test: ## Run the .ci/scripts pytest suite
	@echo "Running .ci/scripts tests..."
	@cd .ci/scripts && python3 -m pytest

# ----------------------------------------------------------------------------
# Combined
# ----------------------------------------------------------------------------

validate: lint test ## Run all local checks (lint + test)
	@echo "✅ All local checks passed"

# ----------------------------------------------------------------------------
# Cleanup
# ----------------------------------------------------------------------------

clean: ## Remove local caches + test artifacts
	@find . -name ".DS_Store" -delete
	@find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	@rm -rf .pytest_cache .ci/scripts/.pytest_cache coverage.xml htmlcov image-ref.txt
	@echo "✅ Cleanup complete"
