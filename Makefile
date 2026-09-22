.PHONY: dev dev-rebuild

dev:
	uv run --python 3.11 python scripts/dev.py

dev-rebuild:
	uv run --python 3.11 python scripts/dev.py --rebuild-images
