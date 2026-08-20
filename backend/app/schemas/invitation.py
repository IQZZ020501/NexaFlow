from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class WorkspaceInvitationCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=255)
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="member", pattern="^(admin|member)$")


class WorkspaceInvitationResponse(BaseModel):
    id: str
    workspace_id: str
    username: str
    email: str
    name: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime
    token: str | None = None
    invite_url: str | None = None


class WorkspaceInvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=20, max_length=255)
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
