import asyncio
import gc
import logging
import sys

from celery import Celery, Task
from celery.signals import after_setup_logger, task_failure, task_postrun

from app.infra.config.settings import Settings
from app.infra.observability.errors import log_error
from app.infra.observability.logger import get_logger, setup_logging
from app.infra.runtime.event_loop import configure_windows_event_loop_policy

logger = get_logger("celery")

_GC_AFTER_TASKS = frozenset(
    {
        "app.agents.run",
        "app.knowledge.run_task",
    }
)

TASK_DISPLAY_NAMES = {
    "app.agents.run": "运行 Agent",
    "app.email.send": "发送邮件",
    "app.knowledge.run_task": "处理知识库任务",
    "app.maintenance.run": "执行周期维护",
    "app.storage.cleanup": "清理持久化文件",
    "app.tools.run": "运行工具",
}

_HIDDEN_MAINTENANCE_TASKS = frozenset({"app.maintenance.run"})
_HIDDEN_MAINTENANCE_LOG_NAMES = _HIDDEN_MAINTENANCE_TASKS | frozenset(
    TASK_DISPLAY_NAMES[name] for name in _HIDDEN_MAINTENANCE_TASKS
)
_HIDDEN_BEAT_ENTRIES = frozenset(
    {
        "recover-frequent-maintenance",
        "recover-minutely-maintenance",
    }
)
_FILTERED_CELERY_LOGGERS = (
    "celery.beat",
    "celery.app.trace",
    "celery.worker.strategy",
)


class NexaFlowTask(Task):
    """Keep Celery's internal task IDs while showing readable log names."""

    def shadow_name(self, args, kwargs, options):
        return display_task_name(self.name)


def display_task_name(task_name: str | None) -> str:
    return TASK_DISPLAY_NAMES.get(task_name or "", task_name or "未知任务")


class _RoutineMaintenanceLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.INFO:
            return True
        if record.name == "celery.beat" and isinstance(record.args, tuple):
            return not any(value in _HIDDEN_BEAT_ENTRIES for value in record.args)
        if record.name in {"celery.app.trace", "celery.worker.strategy"} and isinstance(
            record.args, dict
        ):
            return record.args.get("name") not in _HIDDEN_MAINTENANCE_LOG_NAMES
        return True


_routine_maintenance_log_filter = _RoutineMaintenanceLogFilter()


@after_setup_logger.connect
def hide_routine_maintenance_logs(*, logger, **kwargs) -> None:
    for logger_name in _FILTERED_CELERY_LOGGERS:
        celery_logger = logging.getLogger(logger_name)
        if _routine_maintenance_log_filter not in celery_logger.filters:
            celery_logger.addFilter(_routine_maintenance_log_filter)
    for handler in logger.handlers:
        if _routine_maintenance_log_filter not in handler.filters:
            handler.addFilter(_routine_maintenance_log_filter)


hide_routine_maintenance_logs(logger=logging.getLogger())


def worker_pool_for_platform(platform: str) -> str:
    # billiard's prefork pool requires os.fork() and inherited pipe handles.
    # Windows only has spawn, so prefork workers die with an invalid-handle
    # error in the pool workloop. macOS uses threads so HTTPS clients are not
    # inherited across a fork, while independent runs still overlap.
    if platform == "darwin":
        return "threads"
    return "solo" if platform == "win32" else "prefork"


@task_failure.connect
def log_celery_task_failure(
    *,
    sender,
    task_id: str,
    exception: BaseException,
    **kwargs,
) -> None:
    """Global hook: every failed Celery task lands in the error log."""
    log_error(
        logger,
        "Celery task failed.",
        exception,
        task_id=task_id,
        task_name=display_task_name(sender.name if sender is not None else None),
    )


@task_postrun.connect
def collect_task_garbage(*, sender=None, **kwargs) -> None:
    if getattr(sender, "name", None) in _GC_AFTER_TASKS:
        gc.collect()


def create_celery_app() -> Celery:
    settings = Settings.from_env(require_bootstrap=False)
    setup_logging(level=settings.log_level)
    configure_windows_event_loop_policy()
    app = Celery(
        "app",
        broker=settings.celery_broker_url,
        task_cls=NexaFlowTask,
        include=[
            "app.tasks.knowledge.jobs",
            "app.tasks.agents.jobs",
            "app.tasks.tools.jobs",
            "app.tasks.email.jobs",
            "app.tasks.storage.jobs",
            "app.tasks.maintenance.jobs",
        ],
    )
    app.conf.update(
        accept_content=["json"],
        task_acks_late=True,
        task_ignore_result=True,
        task_reject_on_worker_lost=True,
        task_serializer="json",
        worker_pool=worker_pool_for_platform(sys.platform),
        worker_prefetch_multiplier=1,
        beat_schedule={
            "recover-frequent-maintenance": {
                "task": "app.maintenance.run",
                "schedule": 30.0,
                "args": ("frequent",),
            },
            "recover-minutely-maintenance": {
                "task": "app.maintenance.run",
                "schedule": 60.0,
                "args": ("minutely",),
            },
        },
    )
    return app


celery_app = create_celery_app()
if "app.tasks.knowledge.jobs" not in sys.modules:
    celery_app.loader.import_task_module("app.tasks.knowledge.jobs")


async def publish_task(
    task_name: str,
    args: tuple = (),
    *,
    settings: Settings,
    queue: str | None = None,
    countdown: float | None = None,
    retry: bool = False,
    retry_policy: dict | None = None,
    soft_time_limit: float | None = None,
    time_limit: float | None = None,
    conf_updates: dict | None = None,
    timeout_seconds: float | None = None,
) -> None:
    """Publish work by stable task name.

    The worker-side registry owns execution; producers only build the
    message. Eager execution, failure persistence and recovery policy
    stay in the application use cases that call this helper.
    """
    celery_app.conf.update(broker_url=settings.celery_broker_url, task_always_eager=False)
    if conf_updates:
        celery_app.conf.update(**conf_updates)

    async def _dispatch() -> None:
        await asyncio.to_thread(
            celery_app.send_task,
            task_name,
            args=args,
            queue=queue,
            countdown=countdown,
            retry=retry,
            retry_policy=retry_policy,
            soft_time_limit=soft_time_limit,
            time_limit=time_limit,
        )

    if timeout_seconds is not None:
        await asyncio.wait_for(_dispatch(), timeout=timeout_seconds)
    else:
        await _dispatch()
