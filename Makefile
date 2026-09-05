.PHONY: help install test lint format bench check run-task1 run-task2 run-task3 run-task4

help:
	@echo "install     install dependencies into .venv"
	@echo "test        run the whole pytest suite"
	@echo "lint        ruff check, ruff format check, and mypy"
	@echo "format      apply ruff formatting and safe fixes"
	@echo "check       lint then test"
	@echo "bench       print time to first token and peak held text for task 3"
	@echo "run-task1   MCP server on stdio"
	@echo "run-task2   MCP security gateway on 8080, mock downstream on 8081"
	@echo "run-task3   streaming PII guardrail on 8082"
	@echo "run-task4   model router demo, prints every routing outcome"

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

format:
	uv run ruff format .
	uv run ruff check --fix .

check: lint test

bench:
	uv run python scripts/bench_stream.py

run-task1:
	uv run python -m task1_mcp_server

run-task2:
	uv run python -m task2_mcp_gateway

run-task3:
	uv run python -m task3_stream_guard

run-task4:
	uv run python -m task4_model_router
