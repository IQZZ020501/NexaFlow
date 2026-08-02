## Background worker

Knowledge document preview and indexing are published to Redis through Celery.

```bash
uv run celery -A app.infrastructure.celery:celery_app worker --loglevel=INFO
```

Set `CELERY_BROKER_URL` for Redis. The API process and every worker must share
the configured `KNOWLEDGE_STORAGE_DIR` and `CHROMA_PERSIST_DIR`; separate local
directories cause workers to miss uploaded files or write vectors to a different
collection.
