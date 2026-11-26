"""Jinja syntax inspection and resource-limited rendering for workflow nodes."""

import json
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore

from jinja2 import StrictUndefined, TemplateError, meta, nodes
from jinja2.sandbox import SandboxedEnvironment

REFERENCE_PATTERN = re.compile(r"{{\s*([A-Za-z0-9_-]+)(?:\.([A-Za-z0-9_.-]+))?\s*}}")

MAX_CONTEXT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
MEMORY_LIMIT = 128 * 1024 * 1024
TIMEOUT_SECONDS = 3
_RENDER_SLOTS = BoundedSemaphore(2)
_ENV = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
_ENV.globals.clear()


class _VariableTracker(meta.TrackingCodeGenerator):
    """Jinja's frame analysis tracks variables without evaluating expressions."""

    def visit(self, node, *args, **kwargs):
        if isinstance(node, (nodes.Output, nodes.Expr)):
            return
        return super().visit(node, *args, **kwargs)

    # CodeGenerator visits these directly from statement visitors, bypassing
    # visit(). Its default implementations can fold expressions and filters.
    def visit_EvalContextModifier(self, node, frame):
        pass

    def visit_Filter(self, node, frame):
        pass

    def visit_Call(self, node, frame, forward_caller=False):
        pass


def _check_portable_node(node):
    # Darwin does not enforce a per-process address-space limit. On hosts
    # without one, allow only streaming statements and non-amplifying
    # expressions over bounded JSON. Capturing, calls and arbitrary operators
    # require a host with an OS-enforced allocator budget.
    allowed = (
        nodes.Template,
        nodes.Output,
        nodes.TemplateData,
        nodes.Name,
        nodes.Const,
        nodes.Getattr,
        nodes.Getitem,
        nodes.If,
        nodes.For,
        nodes.Filter,
        nodes.And,
        nodes.Or,
        nodes.Not,
        nodes.Compare,
        nodes.Operand,
    )
    if not isinstance(node, allowed):
        raise ValueError("Template operation requires a memory-limited workflow host.")
    if isinstance(node, nodes.Filter) and (
        node.name not in {"upper", "lower", "trim", "length", "first", "last"}
        or node.args
        or node.kwargs
        or node.dyn_args
        or node.dyn_kwargs
    ):
        raise ValueError("Template filter requires a memory-limited workflow host.")
    if isinstance(node, nodes.For) and (
        node.recursive
        or node.test
        or not isinstance(node.target, nodes.Name)
        or not isinstance(node.iter, (nodes.Name, nodes.Getattr, nodes.Getitem))
    ):
        raise ValueError("Template loop requires a memory-limited workflow host.")


def _parse(template):
    # Reference normalization can expand a 20,000-character template.
    if len(template) > 160_000:
        raise ValueError("Workflow template is too large.")
    try:
        tree = _ENV.parse(template)
        pending = [(tree, 0)]
        count = 0
        while pending:
            node, depth = pending.pop()
            count += 1
            if count > 4096 or depth > 48:
                raise ValueError("Workflow template is too complex.")
            if sys.platform == "darwin":
                _check_portable_node(node)
            pending.extend((child, depth + 1) for child in node.iter_child_nodes())
        return tree
    except (TemplateError, RecursionError, OverflowError) as exc:
        raise ValueError(str(exc)[:250]) from exc


@lru_cache(maxsize=64)
def template_variables(template: str) -> frozenset[str]:
    tree = _parse(template)
    tracker = _VariableTracker(_ENV)
    try:
        tracker.visit(tree)
    except (TemplateError, RecursionError) as exc:
        raise ValueError(str(exc)[:250]) from exc
    return frozenset(tracker.undeclared_identifiers)


def workflow_template_variables(template: str) -> frozenset[str]:
    normalized = REFERENCE_PATTERN.sub("{{ workflow_refs.value }}", template)
    return template_variables(normalized) - {"workflow_refs"}


def _set_process_limits():
    if os.name == "nt":
        import win32api
        import win32job

        job = win32job.CreateJobObject(None, None)
        kind = win32job.JobObjectExtendedLimitInformation
        limits = win32job.QueryInformationJobObject(job, kind)
        limits["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
        )
        limits["ProcessMemoryLimit"] = MEMORY_LIMIT
        win32job.SetInformationJobObject(job, kind, limits)
        win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
        return job  # Retain the handle until rendering finishes.

    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))


def _child():
    _job = _set_process_limits()
    template, variables = json.loads(sys.stdin.buffer.read(MAX_CONTEXT_BYTES + 1))
    compiled = _ENV.from_string(_parse(template))
    output = bytearray()
    for piece in compiled.generate(variables):
        fragment = piece.encode("utf-8")
        if len(output) + len(fragment) > MAX_OUTPUT_BYTES:
            raise ValueError("Workflow template output exceeds the size limit.")
        output.extend(fragment)
    sys.stdout.buffer.write(output)


def render_template(template: str, variables: dict) -> str:
    # Keep large unused node outputs out of both the serialization budget and
    # the renderer process. Jinja's frame analysis handles locally scoped names.
    required = template_variables(template)
    variables = {name: value for name, value in variables.items() if name in required}
    with _RENDER_SLOTS:
        payload = bytearray()
        encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))
        for part in encoder.iterencode((template, variables)):
            if len(payload) + len(part) > MAX_CONTEXT_BYTES:
                raise ValueError("Workflow template context exceeds the size limit.")
            chunk = part.encode("utf-8")
            if len(payload) + len(chunk) > MAX_CONTEXT_BYTES:
                raise ValueError("Workflow template context exceeds the size limit.")
            payload.extend(chunk)
        try:
            result = subprocess.run(
                [sys.executable, "-I", str(Path(__file__).resolve())],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env={
                    key: os.environ[key] for key in ("SystemRoot",) if key in os.environ
                },
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                "Workflow template exceeded its execution deadline."
            ) from exc
        if result.returncode == 2:
            raise ValueError(result.stdout.decode("utf-8"))
        if result.returncode:
            raise ValueError(
                "Workflow template renderer exceeded its resource limits or is unavailable."
            )
        return result.stdout.decode("utf-8")


if __name__ == "__main__":
    try:
        _child()
    except (TemplateError, ValueError, OverflowError, RecursionError) as exc:
        sys.stdout.buffer.write(str(exc)[:250].encode("utf-8", "replace"))
        sys.exit(2)
