from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class WorkspaceInvitationCreateRequest(BaseModel):
    kind: Literal["personal", "generic"] = "personal"
    username: str | None = Field(default=None, min_length=1, max_length=80)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str = Field(default="member", pattern="^(admin|member)$")

    @model_validator(mode="after")
    def validate_recipient(self) -> "WorkspaceInvitationCreateRequest":
        """Require recipient details only for personal invitations."""
        details = (self.username, self.email, self.name)
        if self.kind == "personal" and any(value is None for value in details):
            raise ValueError("Personal invitations require username, email, and name.")
        if self.kind == "generic" and any(value is not None for value in details):
            raise ValueError("Generic invitations cannot specify a recipient.")
        if self.kind == "generic" and self.role == "admin":
            raise ValueError("Generic invitations can only assign the member role.")
        return self


class WorkspaceInvitationResponse(BaseModel):
    id: str
    workspace_id: str
    kind: Literal["personal", "generic"]
    username: str | None = None
    email: str | None = None
    name: str | None = None
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime
    token: str | None = None
    invite_url: str | None = None
    email_delivery_status: Literal[
        "queued",
        "not_configured",
        "not_applicable",
    ] | None = None


class WorkspaceInvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=20, max_length=255)
    username: str | None = Field(default=None, min_length=1, max_length=80)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    password: str = Field(min_length=6, max_length=255)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """Validate that a password contains at least one uppercase letter.
        
        Parameters:
        	value (str): The password to validate.
        
        Returns:
        	str: The unchanged password.
        
        Raises:
        	ValueError: If the password contains no uppercase letters.
        """
        if not any(character.isupper() for character in value):
            raise ValueError("Password must contain at least one uppercase letter.")
        return value
