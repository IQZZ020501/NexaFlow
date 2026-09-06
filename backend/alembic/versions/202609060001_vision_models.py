"""Allow workspace vision-model registrations."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202609060001"
down_revision: str | None = "202609050001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_model_registry_models_type",
        "model",
        type_="check",
    )
    op.create_check_constraint(
        "ck_model_registry_models_type",
        "model",
        "model_type IN ('LLM', 'VISION', 'EMBEDDING', 'RERANKER')",
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE model SET model_type = 'LLM' WHERE model_type = 'VISION'")
    )
    op.drop_constraint(
        "ck_model_registry_models_type",
        "model",
        type_="check",
    )
    op.create_check_constraint(
        "ck_model_registry_models_type",
        "model",
        "model_type IN ('LLM', 'EMBEDDING', 'RERANKER')",
    )
