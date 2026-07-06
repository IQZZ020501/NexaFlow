from dataclasses import dataclass
import os
from pathlib import Path


DEFAULT_JWT_SECRET_KEY = "dev-secret-change-me-please-replace"
DEFAULT_MODEL_SECRET_KEY = "dev-model-secret-change-me-please-replace"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
DEFAULT_KNOWLEDGE_STORAGE_DIR = Path(__file__).resolve().parents[2] / "storage" / "knowledge"


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
    jwt_secret_key: str
    bootstrap_admin_username: str
    bootstrap_admin_email: str
    bootstrap_admin_name: str
    bootstrap_admin_password: str
    default_workspace_name: str
    default_workspace_slug: str
    default_team_name: str
    default_team_slug: str
    model_secret_key: str = DEFAULT_MODEL_SECRET_KEY
    knowledge_storage_dir: Path = DEFAULT_KNOWLEDGE_STORAGE_DIR
    jwt_expires_minutes: int = 60
    cors_origins: tuple[str, ...] = ()
    environment: str = "development"

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
                "postgresql+psycopg://nexaflow:nexaflow@localhost:5432/nexaflow",
            ),
            jwt_secret_key=os.getenv("JWT_SECRET_KEY", DEFAULT_JWT_SECRET_KEY),
            bootstrap_admin_username=os.getenv("BOOTSTRAP_ADMIN_USERNAME", ""),
            bootstrap_admin_email=os.getenv("BOOTSTRAP_ADMIN_EMAIL", ""),
            bootstrap_admin_name=os.getenv("BOOTSTRAP_ADMIN_NAME", ""),
            bootstrap_admin_password=os.getenv("BOOTSTRAP_ADMIN_PASSWORD", ""),
            default_workspace_name=os.getenv("DEFAULT_WORKSPACE_NAME", ""),
            default_workspace_slug=os.getenv("DEFAULT_WORKSPACE_SLUG", ""),
            default_team_name=os.getenv("DEFAULT_TEAM_NAME", ""),
            default_team_slug=os.getenv("DEFAULT_TEAM_SLUG", ""),
            model_secret_key=os.getenv("MODEL_SECRET_KEY", DEFAULT_MODEL_SECRET_KEY),
            knowledge_storage_dir=Path(
                os.getenv("KNOWLEDGE_STORAGE_DIR", str(DEFAULT_KNOWLEDGE_STORAGE_DIR))
            ),
            jwt_expires_minutes=int(os.getenv("JWT_EXPIRES_MINUTES", "60")),
            cors_origins=origins,
            environment=os.getenv("ENVIRONMENT", "development"),
        )
        settings.validate(require_bootstrap=require_bootstrap)
        return settings

    def validate(self, require_bootstrap: bool = True) -> None:
        required = {
            "BOOTSTRAP_ADMIN_USERNAME": self.bootstrap_admin_username,
            "BOOTSTRAP_ADMIN_EMAIL": self.bootstrap_admin_email,
            "BOOTSTRAP_ADMIN_NAME": self.bootstrap_admin_name,
            "BOOTSTRAP_ADMIN_PASSWORD": self.bootstrap_admin_password,
            "DEFAULT_WORKSPACE_NAME": self.default_workspace_name,
            "DEFAULT_WORKSPACE_SLUG": self.default_workspace_slug,
            "DEFAULT_TEAM_NAME": self.default_team_name,
            "DEFAULT_TEAM_SLUG": self.default_team_slug,
        }
        missing = [key for key, value in required.items() if not value]
        if require_bootstrap and missing:
            raise RuntimeError(f"Missing initialization env values: {', '.join(missing)}.")
        if self.environment == "production" and self.jwt_secret_key == DEFAULT_JWT_SECRET_KEY:
            raise RuntimeError("JWT_SECRET_KEY must be set in production.")
        if self.environment == "production" and self.model_secret_key == DEFAULT_MODEL_SECRET_KEY:
            raise RuntimeError("MODEL_SECRET_KEY must be set in production.")
        if self.environment == "production" and self.knowledge_storage_dir == DEFAULT_KNOWLEDGE_STORAGE_DIR:
            raise RuntimeError("KNOWLEDGE_STORAGE_DIR must be set in production.")
