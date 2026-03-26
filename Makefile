.PHONY: install dev test run status report reset clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install package (pip install -e .)
	pip install -e .

dev: ## Install with dev dependencies (pytest, coverage)
	pip install -e ".[dev]"

test: ## Run tests with coverage
	python -m pytest tests/ -v --cov=ai_sdlc_claudecode --cov-report=term-missing

run: ## Run the evolving agent (use ARGS for options, e.g. make run ARGS="--phase 1 --max-cost 10")
	ai-sdlc run $(ARGS)

status: ## Show current state
	ai-sdlc status

report: ## Generate markdown report
	ai-sdlc report

reset: ## Clear state (use ARGS="-f" to skip confirmation)
	ai-sdlc reset $(ARGS)

clean: ## Remove build artifacts
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
