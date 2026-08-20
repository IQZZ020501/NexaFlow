from dataclasses import dataclass
import os
from pathlib import Path

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def _database_url_from_env() -> str:
    configured_url = os.getenv("DATABASE_URL", "").strip()
    if configured_url:
        try:
            parsed_url = make_url(configured_url)
        except ArgumentError as exc:
            raise RuntimeError("Invalid DATABASE_URL.") from exc
        if parsed_url.drivername.startswith("postgresql"):
            expected = {
                "POSTGRES_USER": parsed_url.username,
                "POSTGRES_PASSWORD": parsed_url.password,
                "POSTGRES_DB": parsed_url.database,
            }
            mismatched = [
                key
                for key, actual in expected.items()
                if key in os.environ and os.environ[key] != actual
            ]
            if mismatched:
                raise RuntimeError(
                    "DATABASE_URL must match the configured PostgreSQL components: "
                    f"{', '.join(mismatched)}."
                )
        return configured_url

    try:
        port = int(os.getenv("POSTGRES_PORT", "5432"))
    except ValueError as exc:
        raise RuntimeError("POSTGRES_PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("POSTGRES_PORT must be between 1 and 65535.")
    return URL.create(
        "postgresql+psycopg",
        username=os.getenv("POSTGRES_USER", "nexaflow"),
        password=os.getenv("POSTGRES_PASSWORD", "nexaflow"),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=port,
        database=os.getenv("POSTGRES_DB", "nexaflow"),
    ).render_as_string(hide_password=False)


def load_env_file(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    database_url: str
    bootstrap_admin_username: str
    bootstrap_admin_email: str
    bootstrap_admin_name: str
    bootstrap_admin_password: str
    managed_user_initial_password: str
    jwt_secret_key: str = ""
    model_secret_key: str = ""
    knowledge_storage_dir: Path | None = None
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    celery_broker_url: str = ""
    celery_task_always_eager: bool = False
    mcp_allow_private_networks: bool = False
    mcp_request_timeout_seconds: float = 30.0
    model_request_timeout_seconds: float = 60.0
    agent_tool_timeout_seconds: float = 30.0
    agent_run_timeout_seconds: float = 300.0
    agent_executor_lease_seconds: int = 90
    agent_executor_heartbeat_seconds: int = 30
    agent_event_poll_seconds: float = 0.5
    agent_external_agent_runs_per_minute: int = 60
    agent_external_consumer_runs_per_minute: int = 10
    workflow_sandbox_socket: str = "/run/sandbox/sandbox.sock"
    workflow_sandbox_timeout_seconds: float = 5.0
    jwt_expires_minutes: int = 1440
    refresh_token_expires_days: int = 30
    cors_origins: tuple[str, ...] = ()
    environment: str = "development"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, require_bootstrap: bool = True) -> "Settings":
        load_env_file()
        origins = tuple(
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "").split(",")
            if origin.strip()
        )
        settings = cls(
            database_url=_database_url_from_env(),
            jwt_secret_key=os.getenv("JWT_SECRET_KEY", ""),
            bootstrap_admin_username=os.getenv("BOOTSTRAP_ADMIN_USERNAME", ""),
            bootstrap_admin_email=os.getenv("BOOTSTRAP_ADMIN_EMAIL", ""),
            bootstrap_admin_name=os.getenv("BOOTSTRAP_ADMIN_NAME", ""),
            bootstrap_admin_password=os.getenv("BOOTSTRAP_ADMIN_PASSWORD", ""),
            managed_user_initial_password=os.getenv(
                "MANAGED_USER_INITIAL_PASSWORD",
                "",
            ),
            model_secret_key=os.getenv("MODEL_SECRET_KEY", ""),
            knowledge_storage_dir=(
                Path(os.getenv("KNOWLEDGE_STORAGE_DIR"))
                if os.getenv("KNOWLEDGE_STORAGE_DIR")
                else None
            ),
            qdrant_url=os.getenv("QDRANT_URL", ""),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            celery_broker_url=os.getenv("CELERY_BROKER_URL", ""),
            celery_task_always_eager=os.getenv("CELERY_TASK_ALWAYS_EAGER", "").lower()
            in {"1", "true", "yes"},
            mcp_allow_private_networks=os.getenv("MCP_ALLOW_PRIVATE_NETWORKS", "").lower()
            in {"1", "true", "yes"},
            mcp_request_timeout_seconds=float(
                os.getenv("MCP_REQUEST_TIMEOUT_SECONDS", "30")
            ),
            model_request_timeout_seconds=float(
                os.getenv("MODEL_REQUEST_TIMEOUT_SECONDS", "60")
            ),
            agent_tool_timeout_seconds=float(
                os.getenv("AGENT_TOOL_TIMEOUT_SECONDS", "30")
            ),
            agent_run_timeout_seconds=float(
                os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "300")
            ),
            agent_executor_lease_seconds=int(
                os.getenv("AGENT_EXECUTOR_LEASE_SECONDS", "90")
            ),
            agent_executor_heartbeat_seconds=int(
                os.getenv("AGENT_EXECUTOR_HEARTBEAT_SECONDS", "30")
            ),
            agent_event_poll_seconds=float(
                os.getenv("AGENT_EVENT_POLL_SECONDS", "0.5")
            ),
            agent_external_agent_runs_per_minute=int(
                os.getenv("AGENT_EXTERNAL_AGENT_RUNS_PER_MINUTE", "60")
            ),
            agent_external_consumer_runs_per_minute=int(
                os.getenv("AGENT_EXTERNAL_CONSUMER_RUNS_PER_MINUTE", "10")
            ),
            workflow_sandbox_socket=os.getenv(
                "WORKFLOW_SANDBOX_SOCKET",
                "/run/sandbox/sandbox.sock",
            ),
            workflow_sandbox_timeout_seconds=float(
                os.getenv("WORKFLOW_SANDBOX_TIMEOUT_SECONDS", "5")
            ),
            jwt_expires_minutes=int(os.getenv("JWT_EXPIRES_MINUTES", "1440")),
            refresh_token_expires_days=int(os.getenv("REFRESH_TOKEN_EXPIRES_DAYS", "30")),
            cors_origins=origins,
            environment=os.getenv("ENVIRONMENT", "development"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
        settings.validate(require_bootstrap=require_bootstrap)
        return settings

    def validate(self, require_bootstrap: bool = True) -> None:
        required = {
            "BOOTSTRAP_ADMIN_USERNAME": self.bootstrap_admin_username,
            "BOOTSTRAP_ADMIN_EMAIL": self.bootstrap_admin_email,
            "BOOTSTRAP_ADMIN_NAME": self.bootstrap_admin_name,
            "BOOTSTRAP_ADMIN_PASSWORD": self.bootstrap_admin_password,
        }
        missing = [key for key, value in required.items() if not value]
        if require_bootstrap and missing:
            raise RuntimeError(f"Missing initialization env values: {', '.join(missing)}.")
        if not self.managed_user_initial_password:
            raise RuntimeError(
                "MANAGED_USER_INITIAL_PASSWORD must be set via environment or the .env file."
            )
        if not self.jwt_secret_key:
            raise RuntimeError("JWT_SECRET_KEY must be set via environment or the .env file.")
        if not self.model_secret_key:
            raise RuntimeError("MODEL_SECRET_KEY must be set via environment or the .env file.")
        if not self.knowledge_storage_dir:
            raise RuntimeError("KNOWLEDGE_STORAGE_DIR must be set via environment or the .env file.")
        if not self.qdrant_url:
            raise RuntimeError("QDRANT_URL must be set via environment or the .env file.")
        if not self.celery_broker_url:
            raise RuntimeError("CELERY_BROKER_URL must be set via environment or the .env file.")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise RuntimeError(f"Invalid LOG_LEVEL: {self.log_level}.")
        if self.mcp_request_timeout_seconds <= 0:
            raise RuntimeError("MCP_REQUEST_TIMEOUT_SECONDS must be greater than zero.")
        if self.mcp_request_timeout_seconds > 300:
            raise RuntimeError("MCP_REQUEST_TIMEOUT_SECONDS must not exceed 300.")
        if self.model_request_timeout_seconds <= 0:
            raise RuntimeError("MODEL_REQUEST_TIMEOUT_SECONDS must be greater than zero.")
        if self.model_request_timeout_seconds > 300:
            raise RuntimeError("MODEL_REQUEST_TIMEOUT_SECONDS must not exceed 300.")
        if self.agent_tool_timeout_seconds <= 0:
            raise RuntimeError("AGENT_TOOL_TIMEOUT_SECONDS must be greater than zero.")
        if self.agent_tool_timeout_seconds > 300:
            raise RuntimeError("AGENT_TOOL_TIMEOUT_SECONDS must not exceed 300.")
        if self.agent_run_timeout_seconds <= 0:
            raise RuntimeError("AGENT_RUN_TIMEOUT_SECONDS must be greater than zero.")
        if self.agent_run_timeout_seconds > 1800:
            raise RuntimeError("AGENT_RUN_TIMEOUT_SECONDS must not exceed 1800.")
        if self.agent_executor_lease_seconds < 30:
            raise RuntimeError("AGENT_EXECUTOR_LEASE_SECONDS must be at least 30.")
        if self.agent_executor_heartbeat_seconds <= 0:
            raise RuntimeError("AGENT_EXECUTOR_HEARTBEAT_SECONDS must be greater than zero.")
        if self.agent_executor_heartbeat_seconds * 2 >= self.agent_executor_lease_seconds:
            raise RuntimeError(
                "AGENT_EXECUTOR_HEARTBEAT_SECONDS must be less than half the lease."
            )
        if not 0.1 <= self.agent_event_poll_seconds <= 5:
            raise RuntimeError("AGENT_EVENT_POLL_SECONDS must be between 0.1 and 5.")
        if self.agent_external_agent_runs_per_minute <= 0:
            raise RuntimeError(
                "AGENT_EXTERNAL_AGENT_RUNS_PER_MINUTE must be greater than zero."
            )
        if self.agent_external_consumer_runs_per_minute <= 0:
            raise RuntimeError(
                "AGENT_EXTERNAL_CONSUMER_RUNS_PER_MINUTE must be greater than zero."
            )
        if not self.workflow_sandbox_socket.startswith("/"):
            raise RuntimeError("WORKFLOW_SANDBOX_SOCKET must be an absolute path.")
        if not 0.1 <= self.workflow_sandbox_timeout_seconds <= 30:
            raise RuntimeError(
                "WORKFLOW_SANDBOX_TIMEOUT_SECONDS must be between 0.1 and 30."
            )
        if self.jwt_expires_minutes <= 0:
            raise RuntimeError("JWT_EXPIRES_MINUTES must be greater than zero.")
        if self.refresh_token_expires_days <= 0:
            raise RuntimeError("REFRESH_TOKEN_EXPIRES_DAYS must be greater than zero.")
