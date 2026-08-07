from dataclasses import dataclass
import os
from pathlib import Path


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


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
    jwt_secret_key: str = ""
    model_secret_key: str = ""
    knowledge_storage_dir: Path | None = None
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    celery_broker_url: str = ""
    celery_task_always_eager: bool = False
    mcp_allow_private_networks: bool = False
    mcp_request_timeout_seconds: float = 30.0
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
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql+psycopg://app:app@localhost:5432/app",
            ),
            jwt_secret_key=os.getenv("JWT_SECRET_KEY", ""),
            bootstrap_admin_username=os.getenv("BOOTSTRAP_ADMIN_USERNAME", ""),
            bootstrap_admin_email=os.getenv("BOOTSTRAP_ADMIN_EMAIL", ""),
            bootstrap_admin_name=os.getenv("BOOTSTRAP_ADMIN_NAME", ""),
            bootstrap_admin_password=os.getenv("BOOTSTRAP_ADMIN_PASSWORD", ""),
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
        if self.jwt_expires_minutes <= 0:
            raise RuntimeError("JWT_EXPIRES_MINUTES must be greater than zero.")
        if self.refresh_token_expires_days <= 0:
            raise RuntimeError("REFRESH_TOKEN_EXPIRES_DAYS must be greater than zero.")
