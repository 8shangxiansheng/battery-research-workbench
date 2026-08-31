.PHONY: install test lint api inspect

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src tests apps scripts

api:
	uvicorn apps.api.main:app --reload

inspect:
	python scripts/inspect_raw_data.py \
	  --electrical "data/raw/electrical/小-1-1-264.xlsx" \
	  --ultrasound "data/raw/ultrasound/export - 2024.01.06 - 21.03.01.txt"
