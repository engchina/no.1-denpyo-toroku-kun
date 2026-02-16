.PHONY: install quality format type-check test security

install:
	. .venv/bin/activate && pip install -r requirements.txt

quality:
	. .venv/bin/activate && ruff check denpyo_toroku scripts tests
	. .venv/bin/activate && black --check denpyo_toroku scripts tests

type-check:
	. .venv/bin/activate && mypy denpyo_toroku

format:
	. .venv/bin/activate && ruff check --fix denpyo_toroku scripts tests
	. .venv/bin/activate && black denpyo_toroku scripts tests

test:
	. .venv/bin/activate && pytest

security:
	. .venv/bin/activate && bandit -q -r denpyo_toroku scripts
	. .venv/bin/activate && pip-audit -r requirements.lock
