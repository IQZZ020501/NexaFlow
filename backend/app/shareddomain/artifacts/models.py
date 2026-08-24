from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.base import Base
from app.infrastructure.model_utils import new_id, utc_now


class GeneratedArtifact(Base):
    __tablename__ = "generated_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_generated_artifacts_idempotency",
        ),
        CheckConstraint(
            "format IN ('docx', 'html')",
            name="ck_generated_artifacts_format",
        ),
        CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 5242880",
            name="ck_generated_artifacts_size",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    filename: Mapped[str] = mapped_column(String(120), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    # ponytail: bounded 5 MiB/24h DB blobs; move to ObjectStorage when volume warrants it.
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
