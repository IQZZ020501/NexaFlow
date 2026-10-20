import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

ENV_FILE = Path(__file__).resolve().parents[4] / ".env"


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
    """Process configuration plus stable product/runtime policy defaults.

    Deployment boundaries are loaded from the environment. Stable local service
    and policy values stay here so a normal installation does not need to copy a
    large tuning surface into ``.env``. Existing environment overrides remain
    supported for controlled deployments and backward compatibility.

    ``JWT_SECRET_KEY`` and ``MODEL_SECRET_KEY`` are the only deployment secrets
    that are created once and then kept in PostgreSQL (``platform_secrets``);
    the environment values here only seed an empty store on first start.
    """

    database_url: str
    bootstrap_admin_username: str
    bootstrap_admin_email: str
    bootstrap_admin_name: str
    bootstrap_admin_password: str
    managed_user_initial_password: str
    jwt_secret_key: str = ""
    model_secret_key: str = ""
    knowledge_storage_dir: Path | None = Path("./storage/knowledge")
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str = ""
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False
    mcp_allow_private_networks: bool = False
    mcp_request_timeout_seconds: float = 30.0
    model_request_timeout_seconds: float = 60.0
    agent_tool_timeout_seconds: float = 30.0
    agent_run_timeout_seconds: float = 300.0
    agent_max_turns: int = 8
    agent_max_tool_calls: int = 12
    agent_shell_max_turns: int = 24
    agent_shell_max_tool_calls: int = 64
    agent_shell_run_timeout_seconds: float = 900.0
    agent_max_knowledge_calls: int = 6
    agent_max_knowledge_rounds: int = 3
    agent_max_model_tokens: int = 100_000
    agent_executor_lease_seconds: int = 90
    agent_executor_heartbeat_seconds: int = 30
    agent_event_poll_seconds: float = 0.5
    agent_external_agent_runs_per_minute: int = 60
    agent_external_consumer_runs_per_minute: int = 10
    opensandbox_url: str = "http://127.0.0.1:8088"
    opensandbox_api_key: str = ""
    opensandbox_image: str = "nexaflow/execution:local"
    opensandbox_egress_domains: tuple[str, ...] = ()
    # Live sandboxes allowed across all workers; 0 leaves creation unbounded.
    opensandbox_max_sandboxes: int = 0
    opensandbox_warm_pool_size: int = 0
    opensandbox_max_sandboxes_per_consumer: int = 2
    # Console Runs share the same per-consumer bound as public/API Runs so a
    # single workspace cannot occupy the whole deployment.
    opensandbox_max_sandboxes_per_workspace: int = 2
    # The control plane key grants execution-host control. Plaintext HTTP
    # sends it in every request, so production requires TLS unless the
    # operator explicitly opts out for a loopback-only control plane.
    opensandbox_allow_insecure_http: bool = False
    workflow_sandbox_timeout_seconds: float = 5.0
    # Rendering and Skill execution get their own budget; the workflow code
    # budget is not a safe upper bound for a document renderer.
    artifact_sandbox_timeout_seconds: float = 30.0
    jwt_expires_minutes: int = 1440
    refresh_token_expires_days: int = 30
    public_app_url: str = "http://localhost:8080"
    cors_origins: tuple[str, ...] = ()
    environment: str = "development"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, require_bootstrap: bool = True) -> "Settings":
        load_env_file()
        configured_storage_dir = os.getenv("KNOWLEDGE_STORAGE_DIR")
        knowledge_storage_dir = cls.knowledge_storage_dir
        if configured_storage_dir is not None:
            knowledge_storage_dir = (
                Path(configured_storage_dir) if configured_storage_dir else None
            )
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
            knowledge_storage_dir=knowledge_storage_dir,
            qdrant_url=os.getenv("QDRANT_URL", cls.qdrant_url),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            celery_broker_url=os.getenv("CELERY_BROKER_URL", cls.celery_broker_url),
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
            agent_max_turns=int(os.getenv("AGENT_MAX_TURNS", "8")),
            agent_max_tool_calls=int(os.getenv("AGENT_MAX_TOOL_CALLS", "12")),
            agent_shell_max_turns=int(os.getenv("AGENT_SHELL_MAX_TURNS", "24")),
            agent_shell_max_tool_calls=int(os.getenv("AGENT_SHELL_MAX_TOOL_CALLS", "64")),
            agent_shell_run_timeout_seconds=float(os.getenv("AGENT_SHELL_RUN_TIMEOUT_SECONDS", "900")),
            agent_max_knowledge_calls=int(
                os.getenv("AGENT_MAX_KNOWLEDGE_CALLS", "6")
            ),
            agent_max_knowledge_rounds=int(
                os.getenv("AGENT_MAX_KNOWLEDGE_ROUNDS", "3")
            ),
            agent_max_model_tokens=int(
                os.getenv("AGENT_MAX_MODEL_TOKENS", "100000")
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
            opensandbox_url=os.getenv(
                "OPENSANDBOX_URL", "http://127.0.0.1:8088"
            ).rstrip("/"),
            opensandbox_api_key=os.getenv("OPENSANDBOX_API_KEY", ""),
            opensandbox_image=os.getenv(
                "OPENSANDBOX_IMAGE", "nexaflow/execution:local"
            ),
            opensandbox_egress_domains=tuple(
                value.strip()
                for value in os.getenv("OPENSANDBOX_EGRESS_DOMAINS", "").split(",")
                if value.strip()
            ),
            opensandbox_max_sandboxes=int(
                os.getenv("OPENSANDBOX_MAX_SANDBOXES", "0")
            ),
            opensandbox_warm_pool_size=int(os.getenv("OPENSANDBOX_WARM_POOL_SIZE", "0")),
            opensandbox_max_sandboxes_per_consumer=int(os.getenv("OPENSANDBOX_MAX_SANDBOXES_PER_CONSUMER", "2")),
            opensandbox_max_sandboxes_per_workspace=int(
                os.getenv("OPENSANDBOX_MAX_SANDBOXES_PER_WORKSPACE", "2")
            ),
            opensandbox_allow_insecure_http=os.getenv(
                "OPENSANDBOX_ALLOW_INSECURE_HTTP", ""
            ).strip().lower()
            in {"1", "true", "yes", "on"},
            workflow_sandbox_timeout_seconds=float(
                os.getenv("WORKFLOW_SANDBOX_TIMEOUT_SECONDS", "5")
            ),
            artifact_sandbox_timeout_seconds=float(
                os.getenv("ARTIFACT_SANDBOX_TIMEOUT_SECONDS", "30")
            ),
            jwt_expires_minutes=int(os.getenv("JWT_EXPIRES_MINUTES", "1440")),
            refresh_token_expires_days=int(os.getenv("REFRESH_TOKEN_EXPIRES_DAYS", "30")),
            public_app_url=os.getenv("PUBLIC_APP_URL", cls.public_app_url).rstrip("/"),
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
        # JWT_SECRET_KEY and MODEL_SECRET_KEY are not required here: the
        # application resolves them from platform_secrets at startup, using the
        # environment value only to seed a missing key.
        if not self.knowledge_storage_dir:
            raise RuntimeError("KNOWLEDGE_STORAGE_DIR must be set via environment or the .env file.")
        if not self.qdrant_url:
            raise RuntimeError("QDRANT_URL must be set via environment or the .env file.")
        if not self.celery_broker_url:
            raise RuntimeError("CELERY_BROKER_URL must be set via environment or the .env file.")
        public_url = urlsplit(self.public_app_url)
        if public_url.scheme not in {"http", "https"} or not public_url.netloc:
            raise RuntimeError("PUBLIC_APP_URL must be an absolute HTTP(S) URL.")
        if public_url.path not in {"", "/"} or public_url.query or public_url.fragment:
            raise RuntimeError("PUBLIC_APP_URL must not include a path, query, or fragment.")
        if self.environment == "production" and public_url.scheme != "https":
            raise RuntimeError("PUBLIC_APP_URL must use HTTPS in production.")
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
        if not 1 <= self.agent_max_turns <= 64:
            raise RuntimeError("AGENT_MAX_TURNS must be between 1 and 64.")
        if not 1 <= self.agent_shell_max_turns <= 64:
            raise RuntimeError("AGENT_SHELL_MAX_TURNS must be between 1 and 64.")
        if not 1 <= self.agent_shell_max_tool_calls <= 128:
            raise RuntimeError("AGENT_SHELL_MAX_TOOL_CALLS must be between 1 and 128.")
        if not 0 < self.agent_shell_run_timeout_seconds <= 1800:
            raise RuntimeError("AGENT_SHELL_RUN_TIMEOUT_SECONDS must be between 0 and 1800.")
        if not 1 <= self.agent_max_tool_calls <= 128:
            raise RuntimeError("AGENT_MAX_TOOL_CALLS must be between 1 and 128.")
        if not 1 <= self.agent_max_knowledge_calls <= self.agent_max_tool_calls:
            raise RuntimeError(
                "AGENT_MAX_KNOWLEDGE_CALLS must be between 1 and "
                "AGENT_MAX_TOOL_CALLS."
            )
        if not 1 <= self.agent_max_knowledge_rounds <= self.agent_max_turns:
            raise RuntimeError(
                "AGENT_MAX_KNOWLEDGE_ROUNDS must be between 1 and AGENT_MAX_TURNS."
            )
        if not 1 <= self.agent_max_model_tokens <= 1_000_000:
            raise RuntimeError(
                "AGENT_MAX_MODEL_TOKENS must be between 1 and 1000000."
            )
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
        from urllib.parse import urlparse

        from app.infra.execution.network import validate_egress_domain

        endpoint = urlparse(self.opensandbox_url)
        try:
            endpoint_port = endpoint.port
        except ValueError as exc:
            raise RuntimeError("OPENSANDBOX_URL contains an invalid port.") from exc
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or endpoint.path not in {"", "/"}
            or endpoint_port == 0
        ):
            raise RuntimeError(
                "OPENSANDBOX_URL must be a trusted HTTP(S) control-plane origin."
            )
        if self.environment == "production" and self.opensandbox_api_key and not re.fullmatch(
            r"[^\s]+@sha256:[a-f0-9]{64}", self.opensandbox_image
        ):
            raise RuntimeError("OPENSANDBOX_IMAGE must use an immutable sha256 digest in production.")
        try:
            for domain in self.opensandbox_egress_domains:
                if validate_egress_domain(domain) != domain:
                    raise ValueError("Deployment egress domains must be lowercase.")
        except ValueError as exc:
            raise RuntimeError(
                "OPENSANDBOX_EGRESS_DOMAINS must contain domain names, not URLs or IP ranges."
            ) from exc
        if self.opensandbox_max_sandboxes < 0:
            raise RuntimeError("OPENSANDBOX_MAX_SANDBOXES must not be negative.")
        if self.opensandbox_warm_pool_size < 0 or (self.opensandbox_max_sandboxes and self.opensandbox_warm_pool_size >= self.opensandbox_max_sandboxes):
            raise RuntimeError("OPENSANDBOX_WARM_POOL_SIZE must be nonnegative and leave capacity for active sandboxes.")
        if self.opensandbox_warm_pool_size and not self.opensandbox_max_sandboxes:
            raise RuntimeError(
                "OPENSANDBOX_WARM_POOL_SIZE requires OPENSANDBOX_MAX_SANDBOXES: a warm pool "
                "without a host limit bypasses capacity accounting entirely."
            )
        if not 1 <= self.opensandbox_max_sandboxes_per_consumer <= 2:
            raise RuntimeError("OPENSANDBOX_MAX_SANDBOXES_PER_CONSUMER must be between 1 and 2.")
        if not 1 <= self.opensandbox_max_sandboxes_per_workspace <= 8:
            raise RuntimeError(
                "OPENSANDBOX_MAX_SANDBOXES_PER_WORKSPACE must be between 1 and 8."
            )
        if self.environment == "production" and self.opensandbox_api_key:
            # An unbounded host limit lets one burst of Runs exhaust the
            # execution host, which fails every tenant at once.
            if self.opensandbox_max_sandboxes <= 0:
                raise RuntimeError(
                    "OPENSANDBOX_MAX_SANDBOXES must be a positive host limit in production."
                )
            if endpoint.scheme != "https" and not self.opensandbox_allow_insecure_http:
                raise RuntimeError(
                    "OPENSANDBOX_URL must use https in production: the control-plane key "
                    "is sent on every request. Set OPENSANDBOX_ALLOW_INSECURE_HTTP=1 only "
                    "for a loopback control plane."
                )
        if not 0.1 <= self.workflow_sandbox_timeout_seconds <= 30:
            raise RuntimeError(
                "WORKFLOW_SANDBOX_TIMEOUT_SECONDS must be between 0.1 and 30."
            )
        if not 0.1 <= self.artifact_sandbox_timeout_seconds <= 300:
            raise RuntimeError(
                "ARTIFACT_SANDBOX_TIMEOUT_SECONDS must be between 0.1 and 300."
            )
        if self.jwt_expires_minutes <= 0:
            raise RuntimeError("JWT_EXPIRES_MINUTES must be greater than zero.")
        if self.refresh_token_expires_days <= 0:
            raise RuntimeError("REFRESH_TOKEN_EXPIRES_DAYS must be greater than zero.")
