.PHONY: lint typecheck test coverage migrate dev build

lint:
	ruff check brainycat/ tests/
	ruff format --check brainycat/ tests/

typecheck:
	mypy brainycat/

test:
	pytest tests/

coverage:
	pytest tests/ --cov-report=html

migrate:
	alembic upgrade head

dev:
	uvicorn brainycat.web:app --reload --host 0.0.0.0 --port 8000

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down
