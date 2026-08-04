"""model provider credentials

Revision ID: 202608050002
Revises: 202608050001
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608050002"
down_revision: str | None = "202608050001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVIDER_TYPE_CONSTRAINT = "ck_model_registry_models_provider_type"


def upgrade() -> None:
    op.add_column(
        "model",
        sa.Column(
            "credential_config",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "model",
        sa.Column(
            "credential_secret_hints",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.alter_column("model", "credential_config", server_default=None)
    op.alter_column("model", "credential_secret_hints", server_default=None)

    op.drop_constraint(PROVIDER_TYPE_CONSTRAINT, "model", type_="check")
    op.execute(
        sa.text(
            """
            UPDATE model
            SET provider_type = CASE provider
                WHEN 'model_anthropic_provider' THEN 'anthropic'
                WHEN 'model_aws_bedrock_provider' THEN 'bedrock'
                WHEN 'model_azure_provider' THEN 'azure_openai'
                WHEN 'model_deepseek_provider' THEN 'deepseek'
                WHEN 'model_gemini_provider' THEN 'google_genai'
                ELSE provider_type
            END
            WHERE provider IN (
                'model_anthropic_provider',
                'model_aws_bedrock_provider',
                'model_azure_provider',
                'model_deepseek_provider',
                'model_gemini_provider'
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE model
            SET provider_type = 'ollama'
            WHERE provider = 'model_ollama_provider'
              AND model_type IN ('LLM', 'EMBEDDING')
            """
        )
    )
    op.create_check_constraint(
        PROVIDER_TYPE_CONSTRAINT,
        "model",
        "provider_type IN ('openai_compatible', 'anthropic', 'bedrock', "
        "'azure_openai', 'deepseek', 'google_genai', 'ollama')",
    )


def downgrade() -> None:
    op.drop_constraint(PROVIDER_TYPE_CONSTRAINT, "model", type_="check")
    op.execute(
        sa.text(
            """
            UPDATE model
            SET provider_type = 'openai_compatible'
            WHERE provider_type IN (
                'anthropic',
                'bedrock',
                'azure_openai',
                'deepseek',
                'google_genai',
                'ollama'
            )
            """
        )
    )
    op.create_check_constraint(
        PROVIDER_TYPE_CONSTRAINT,
        "model",
        "provider_type IN ('openai_compatible')",
    )
    op.drop_column("model", "credential_secret_hints")
    op.drop_column("model", "credential_config")
