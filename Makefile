.PHONY: dev dev-rebuild sandbox-image

dev:
	uv run --python 3.11 python scripts/dev.py

dev-rebuild:
	uv run --python 3.11 python scripts/dev.py --rebuild-images

sandbox-image:
	docker build -f deploy/dockerfiles/sandbox.Dockerfile -t $${OPENSANDBOX_IMAGE:-nexaflow/execution:local} .
