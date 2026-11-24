"""Bound synchronous model probes before the provider SDK buffers or decodes the body."""

from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from time import monotonic

import httpx

from app.ports.llm import ModelProviderError, ModelProviderTimeoutError

MAX_PROBE_BYTES = 1024 * 1024
MAX_PROBE_EVENTS = 256
MAX_RERANK_BYTES = 2 * 1024 * 1024


class ResponseBudget:
    def __init__(self, byte_limit: int, timeout: float):
        self.remaining_bytes = byte_limit
        self.deadline = monotonic() + timeout

    def remaining_time(self, operation_timeout: float | None = None) -> float:
        seconds = self.deadline - monotonic()
        if seconds <= 0:
            raise ModelProviderTimeoutError("Model request timed out.")
        return (
            min(seconds, operation_timeout)
            if operation_timeout is not None
            else seconds
        )

    def checked_chunks(self, chunks: Iterable[bytes]) -> Iterator[bytes]:
        for chunk in chunks:
            self.remaining_time()
            self.remaining_bytes -= len(chunk)
            if self.remaining_bytes < 0:
                raise ModelProviderError("Model response exceeds the size limit.")
            yield chunk
        self.remaining_time()

    def prepare_request(self, request: httpx.Request) -> None:
        # Avoid unbounded allocations inside compression codecs before byte counting.
        request.headers["Accept-Encoding"] = "identity"
        remaining = self.remaining_time()
        timeouts = request.extensions.get("timeout", {})
        request.extensions["timeout"] = {
            key: min(value, remaining) if value is not None else remaining
            for key, value in timeouts.items()
        }

    def limit_response(self, response: httpx.Response) -> None:
        encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if encoding != "identity":
            raise ModelProviderError("Model response uses an unsupported content encoding.")
        response.stream = _LimitedStream(response.stream, self)

    def hooks(self):
        return {"request": [self.prepare_request], "response": [self.limit_response]}


class _LimitedStream(httpx.SyncByteStream):
    def __init__(self, stream, budget):
        self.stream = stream
        self.budget = budget

    def __iter__(self):
        yield from self.budget.checked_chunks(self.stream)

    def close(self):
        self.stream.close()


class ProbeBudget(ResponseBudget):
    def __init__(self, timeout):
        super().__init__(MAX_PROBE_BYTES, timeout)
        self.resources = ExitStack()


active_probe: ContextVar[ProbeBudget | None] = ContextVar("model_probe", default=None)


@contextmanager
def model_probe(timeout: float):
    budget = ProbeBudget(timeout)
    token = active_probe.set(budget)
    try:
        with budget.resources:
            yield budget
    finally:
        active_probe.reset(token)
