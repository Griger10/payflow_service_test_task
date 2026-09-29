set shell := ["sh", "-cu"]
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

default:
    @just --list

check: format-check lint typecheck test

format-check:
    uv run --locked ruff format --check .

lint:
    uv run --locked ruff check .

typecheck:
    uv run --locked mypy

test *args:
    uv run --locked pytest -q {{ args }}

fix:
    uv run --locked ruff format .
    uv run --locked ruff check --fix .

db:
    docker compose up -d --wait postgres
